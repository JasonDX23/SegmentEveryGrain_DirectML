"""Code-free Windows desktop workspace for grain segmentation."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import traceback

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np
from PIL import Image
import torch
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from . import interactions as si
from .directml import sam_checkpoint_path
from .unet import load_unet
from .inference import segment_image, SegmentationResult

APP_DIR=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'SegmentEveryGrainDesktop'


class DesktopApp:
    def __init__(self,root,config):
        self.root=root;self.config=config
        self.root.title('Segment Every Grain')
        width=min(1380,self.root.winfo_screenwidth()-80)
        height=min(880,self.root.winfo_screenheight()-100)
        self.root.geometry(f'{width}x{height}');self.root.minsize(1100,740)
        self.queue=queue.Queue();self.busy=False;self.dirty=False
        self.models=None;self.model_key=None;self.image=None;self.image_path=None
        self.result=None;self.plot=None;self.session=None
        self.mode=tk.StringVar(value='select');self.variant=tk.StringVar(value=config.get('variant','large'))
        self.length=tk.StringVar(value='10');self.unit=tk.StringVar(value='mm')
        self.minimum=tk.StringVar(value='50');self.status=tk.StringVar(value='Open an image to begin.')
        self.scale_status=tk.StringVar(value='Not calibrated')
        self.count=tk.StringVar(value='No masks yet')
        self.table_status=tk.StringVar(value='Segment an image to see grain measurements here.')
        self.file_label=tk.StringVar(value='No image open')
        self.table_data=None;self.table_key=None;self.table_job=None;self.sort_column=None;self.sort_reverse=False
        self._build();root.protocol('WM_DELETE_WINDOW',self.close)
        self.unit.trace_add('write',self.unit_changed)
        self.sync_controls()
        root.bind('<Control-o>',lambda event:self.open_image())
        root.bind('<Control-Shift-O>',lambda event:self.open_project())
        root.bind('<Control-s>',lambda event:self.save())
        root.after(100,self.poll)

    def _build(self):
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10),background='#f4f6f5')
        style.configure('TButton',padding=(10,7))
        style.configure('Accent.TButton',background='#126b60',foreground='white',padding=(16,9))
        style.map('Accent.TButton',background=[('disabled','#cedbd7'),('active','#0d574e')],foreground=[('disabled','#596e67')])
        style.configure('TLabel',foreground='#243d36')
        style.configure('Muted.TLabel',foreground='#5c7069',font=('Segoe UI',9))
        style.configure('Section.TLabel',font=('Segoe UI',11,'bold'),foreground='#17332e')
        style.map('TRadiobutton',background=[('disabled','#f4f6f5'),('active','#e7eeeb')])
        style.map('TCombobox',fieldbackground=[('readonly','white')])
        style.configure('Treeview',background='white',fieldbackground='white',foreground='#243d36',rowheight=29,borderwidth=0)
        style.configure('Treeview.Heading',background='#e7eeeb',foreground='#243d36',font=('Segoe UI',9,'bold'),padding=(10,8))
        style.map('Treeview',background=[('selected','#126b60')],foreground=[('selected','white')])
        style.configure('Title.TLabel',font=('Segoe UI',20,'bold'),foreground='#17332e')
        top=ttk.Frame(self.root,padding=(20,14));top.pack(fill='x')
        ttk.Label(top,text='Segment Every Grain',style='Title.TLabel').pack(side='left')
        adapter=self.config.get('adapter_name','CPU') if self.config['backend']=='directml' else 'CPU'
        ttk.Label(top,text=f'{adapter}  ·  {self.config["backend"].upper()}').pack(side='left',padx=20)
        ttk.Button(top,text='Machine setup',command=self.setup).pack(side='right')
        bar=ttk.Frame(self.root,padding=(20,0,20,12));bar.pack(fill='x')
        self.open_button=ttk.Button(bar,text='Open image',command=self.open_image);self.open_button.pack(side='left')
        self.project_button=ttk.Button(bar,text='Open saved project',command=self.open_project);self.project_button.pack(side='left',padx=8)
        ttk.Label(bar,textvariable=self.file_label,style='Muted.TLabel').pack(side='left',padx=12)
        self.run_button=ttk.Button(bar,text='Segment image',style='Accent.TButton',command=self.run)
        self.run_button.pack(side='left',padx=12)
        self.save_button=ttk.Button(bar,text='Save project & results',command=self.save)
        self.save_button.pack(side='right')
        bottom=ttk.Frame(self.root,padding=(20,8));bottom.pack(side='bottom',fill='x')
        self.progress=ttk.Progressbar(bottom,mode='indeterminate',length=130);self.progress.pack(side='right')
        ttk.Label(bottom,textvariable=self.status,wraplength=1000).pack(side='left')
        workspace=ttk.Frame(self.root);workspace.pack(fill='both',expand=True,padx=20)
        side_host=ttk.Frame(workspace,width=260);side_host.pack(side='left',fill='y');side_host.pack_propagate(False)
        side_canvas=tk.Canvas(side_host,width=242,highlightthickness=0,bg='#f4f6f5')
        side_scroll=ttk.Scrollbar(side_host,orient='vertical',command=side_canvas.yview)
        side_scroll.pack(side='right',fill='y');side_canvas.pack(side='left',fill='both',expand=True)
        side_canvas.configure(yscrollcommand=side_scroll.set)
        side=ttk.Frame(side_canvas,padding=(0,8,8,8))
        side_canvas.create_window((0,0),window=side,anchor='nw',width=242)
        side.bind('<Configure>',lambda event:side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        ttk.Label(side,text='1  Segment',style='Section.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(side,text='Model · large = detailed, tiny = fast',style='Muted.TLabel').pack(anchor='w',pady=(0,4))
        self.model_control=ttk.Combobox(side,textvariable=self.variant,values=['large','tiny'],state='readonly')
        self.model_control.pack(fill='x')
        ttk.Label(side,text='Minimum grain area (px²)',style='Muted.TLabel').pack(anchor='w',pady=(10,4))
        self.area_control=ttk.Entry(side,textvariable=self.minimum);self.area_control.pack(fill='x')
        ttk.Separator(side).pack(fill='x',pady=14)
        side_root=side
        tools=ttk.Notebook(side_root);tools.pack(fill='both',expand=True)
        editor_side=ttk.Frame(tools,padding=(8,12,8,8))
        calibration_side=ttk.Frame(tools,padding=(8,12,8,8))
        tools.add(editor_side,text='Review & edit');tools.add(calibration_side,text='Calibrate')
        side=editor_side
        ttk.Label(side,text='2  Review & edit',style='Section.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(side,textvariable=self.count,foreground='#126b60').pack(anchor='w',pady=(0,8))
        self.manual_button=ttk.Button(side,text='Start manual editor',command=self.manual);self.manual_button.pack(fill='x',pady=(0,8))
        self.edit_controls=[]
        for value,title in [('select','Select masks'),('add','Add mask with one click'),('foreground','Place foreground prompts'),('background','Place background prompts')]:
            control=ttk.Radiobutton(side,text=title,variable=self.mode,value=value,command=self.mode_changed)
            control.pack(anchor='w',pady=4);self.edit_controls.append(control)
        ttk.Button(side,text='Create mask from prompts',command=self.create_mask).pack(fill='x',pady=(10,4))
        ttk.Button(side,text='Delete selected masks',command=lambda:self.action('delete_grains')).pack(fill='x',pady=4)
        ttk.Button(side,text='Merge selected masks',command=lambda:self.action('merge_grains')).pack(fill='x',pady=4)
        ttk.Button(side,text='Undo last added mask',command=lambda:self.action('undo_grain')).pack(fill='x',pady=4)
        ttk.Button(side,text='Clear selection / prompts',command=lambda:self.action('clear_all',False)).pack(fill='x',pady=4)
        side=calibration_side
        ttk.Label(side,text='3  Calibrate sizes',style='Section.TLabel').pack(anchor='w')
        ruler_control=ttk.Radiobutton(side,text='Draw ruler reference',variable=self.mode,value='ruler',command=self.mode_changed)
        ruler_control.pack(anchor='w',pady=(12,4));self.edit_controls.append(ruler_control)
        ttk.Label(side,text='Known interval in the image:',wraplength=210).pack(anchor='w',pady=(10,4))
        row=ttk.Frame(side);row.pack(fill='x')
        ttk.Entry(row,textvariable=self.length,width=10).pack(side='left')
        ttk.Combobox(row,textvariable=self.unit,values=['mm','cm'],state='readonly',width=5).pack(side='left',padx=6)
        ttk.Button(side,text='Apply ruler length',command=self.apply_scale).pack(fill='x',pady=8)
        ttk.Label(side,textvariable=self.scale_status,wraplength=210,foreground='#126b60').pack(anchor='w',pady=4)
        ttk.Label(side,text='Choose Draw ruler reference, then drag between two known ruler marks. No keyboard modifier is needed.',wraplength=210).pack(anchor='w',pady=8)
        ttk.Label(side,text='The measurement table updates automatically. Without a ruler reference, sizes are shown in pixels.',wraplength=185,style='Muted.TLabel').pack(anchor='w',pady=10)
        ttk.Label(editor_side,text='Click masks to select. Turn off plot zoom and pan before editing.',wraplength=185,style='Muted.TLabel').pack(anchor='w',pady=10)
        split=ttk.Panedwindow(workspace,orient='vertical');split.pack(side='left',fill='both',expand=True,padx=(12,0))
        area=ttk.Frame(split);split.add(area,weight=3)
        results=ttk.Frame(split,padding=(12,10));split.add(results,weight=2)
        heading=ttk.Frame(results);heading.pack(fill='x',pady=(0,8))
        ttk.Label(heading,text='Grain measurements',style='Section.TLabel').pack(side='left')
        self.csv_button=ttk.Button(heading,text='Export CSV…',command=self.export_csv);self.csv_button.pack(side='right')
        ttk.Label(results,textvariable=self.table_status,style='Muted.TLabel').pack(anchor='w',pady=(0,8))
        table_host=ttk.Frame(results);table_host.pack(fill='both',expand=True)
        table_host.rowconfigure(0,weight=1);table_host.columnconfigure(0,weight=1)
        self.table=ttk.Treeview(table_host,show='headings',height=6,selectmode='extended')
        self.table.grid(row=0,column=0,sticky='nsew')
        vscroll=ttk.Scrollbar(table_host,orient='vertical',command=self.table.yview);vscroll.grid(row=0,column=1,sticky='ns')
        hscroll=ttk.Scrollbar(table_host,orient='horizontal',command=self.table.xview);hscroll.grid(row=1,column=0,sticky='ew')
        self.table.configure(yscrollcommand=vscroll.set,xscrollcommand=hscroll.set)
        self.table.tag_configure('alternate',background='#f2f6f4')
        ttk.Label(results,text='Click a heading to sort · Scroll sideways for all CSV columns · Centroids use image pixels',style='Muted.TLabel').pack(anchor='w',pady=(7,0))
        self.split_fraction=.60
        def fit_split(event=None):
            height=split.winfo_height()
            if height>400:split.sashpos(0,min(height-220,max(220,int(height*self.split_fraction))))
        split.bind('<Configure>',lambda event:self.root.after_idle(fit_split))
        split.bind('<ButtonRelease-1>',lambda event:setattr(self,'split_fraction',split.sashpos(0)/max(1,split.winfo_height())))
        self.figure=Figure(figsize=(9,7),facecolor='white')
        self.canvas=FigureCanvasTkAgg(self.figure,master=area)
        self.toolbar=NavigationToolbar2Tk(self.canvas,area,pack_toolbar=False);self.toolbar.update();self.toolbar.pack(side='bottom',fill='x')
        self.canvas.get_tk_widget().pack(side='top',fill='both',expand=True)
        ax=self.figure.add_subplot();ax.text(.5,.5,'Open an image, then select Segment image.',ha='center',va='center',transform=ax.transAxes,color='#577069',fontsize=15);ax.axis('off');self.canvas.draw()
        def bind_scroll(widget):
            widget.bind('<MouseWheel>',lambda event:side_canvas.yview_scroll(-int(event.delta/120),'units'))
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(side_root)
        self.edit_controls.extend(child for page in (editor_side,calibration_side) for child in page.winfo_children()
                                  if isinstance(child,ttk.Button) and child is not self.manual_button)

    def mode_changed(self):
        if self.plot:
            self.plot.clear_all();self.plot.update()
        hints={'select':'Click masks to select or unselect them.','add':'Click inside an unmasked grain to generate its mask.',
               'foreground':'Place one or more points inside the desired grain, then Create mask.',
               'background':'Place points outside the desired outline, then Create mask.',
               'ruler':'Enter the real ruler interval length, then drag along that interval.'}
        self.status.set(hints[self.mode.get()])

    def unsaved_ok(self):
        return not self.dirty or messagebox.askyesno('Unsaved edits','Continue without saving the current edits?',parent=self.root)

    def open_image(self):
        if self.busy or not self.unsaved_ok():return
        path=filedialog.askopenfilename(title='Open grain image',filetypes=[('Images','*.jpg *.jpeg *.png *.tif *.tiff *.bmp'),('All files','*.*')])
        if path:self.load_path(path)

    def load_path(self,path):
        try:
            with Image.open(path) as im:self.image=np.array(im.convert('RGB'))
            self.image_path=Path(path);self.result=None;self.session=None;self.dirty=False
            if self.plot:self.plot.deactivate();self.plot=None
            self.figure.clear();ax=self.figure.add_subplot();ax.imshow(self.image);ax.axis('off');self.figure.tight_layout(pad=0);self.canvas.draw()
            self.count.set('No masks yet');self.scale_status.set('Not calibrated')
            name=self.image_path.name
            if len(name)>35:name=name[:25]+'…'+self.image_path.suffix
            self.file_label.set(f'{name} · {self.image.shape[1]} × {self.image.shape[0]} px')
            self.clear_measurements();self.sync_controls()
            self.status.set(f'{self.image_path.name} · {self.image.shape[1]} × {self.image.shape[0]} pixels. Ready to segment.')
        except Exception as exc:messagebox.showerror('Could not open image',str(exc),parent=self.root)

    def start_task(self,operation,worker):
        if self.busy:return
        self.busy=True;self.status.set(operation);self.progress.start(12)
        self.sync_controls()
        for b in (self.run_button,self.open_button,self.save_button):b.state(['disabled'])
        def work():
            try:self.queue.put(('ready',worker()))
            except Exception:self.queue.put(('error',traceback.format_exc()))
        threading.Thread(target=work,daemon=True).start()

    def load_models(self,variant):
        key=(variant,self.config['backend'],self.config.get('adapter_name'))
        if self.model_key==key:return self.models
        if self.config['backend']=='directml':
            from .directml import get_device
            device=get_device(self.config.get('adapter_name','RX 6600'))
        else:device=torch.device('cpu')
        unet=load_unet(str(Path(__file__).parent/'models/seg_model_smooth_labels.pt'),device=device)
        checkpoint=sam_checkpoint_path(variant)
        sam=build_sam2(f'configs/sam2.1/sam2.1_hiera_{"l" if variant=="large" else "t"}.yaml',str(checkpoint),device=device)
        self.models=(unet,sam,device);self.model_key=key
        return self.models

    def run(self):
        if self.image is None:
            self.open_image()
            if self.image is None:return
        if not self.unsaved_ok():return
        try:
            area=int(self.minimum.get())
            if area<1:raise ValueError()
        except ValueError:
            messagebox.showerror('Grain area','Enter a positive whole number for minimum grain area.',parent=self.root);return
        image=self.image;path=self.image_path;variant=self.variant.get()
        def work():
            models=self.load_models(variant)
            if max(image.shape[:2])>2200:
                from .segmenteverygrain import predict_large_image
                t=time.perf_counter()
                with torch.no_grad():
                    polygons,_,_=predict_large_image(str(path),models[0],sam=models[1],min_area=area,
                        patch_size=2000,overlap=300,remove_edge_grains=False,verbose=False)
                result=SegmentationResult(image,polygons,None,models[1],models[2],time.perf_counter()-t)
            else:result=segment_image(image,models=models,min_area=area)
            predictor=SAM2ImagePredictor(models[1])
            with torch.no_grad():predictor.set_image(image)
            return result,predictor,None
        self.start_task('Segmenting image. Large images are processed in tiles; please wait…',work)

    def manual(self):
        if self.busy:return
        if self.image is None:
            self.open_image()
            if self.image is None:return
        if not self.unsaved_ok():return
        image=self.image;variant=self.variant.get()
        def work():
            models=self.load_models(variant);predictor=SAM2ImagePredictor(models[1])
            with torch.no_grad():predictor.set_image(image)
            return SegmentationResult(image,[],None,models[1],models[2],0),predictor,None
        self.start_task('Preparing the manual mask editor…',work)

    def poll(self):
        try:
            while True:
                kind,payload=self.queue.get_nowait()
                self.busy=False;self.progress.stop()
                for b in (self.run_button,self.open_button,self.save_button):b.state(['!disabled'])
                if kind=='error':
                    APP_DIR.mkdir(parents=True,exist_ok=True);(APP_DIR/'last_error.txt').write_text(payload)
                    self.status.set('Operation failed. Details saved in application data.')
                    messagebox.showerror('Operation failed',payload[-1600:],parent=self.root)
                else:
                    self.result,predictor,session=payload
                    self.mount_editor(predictor,session)
                self.sync_controls()
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def mount_editor(self,predictor,session=None):
        if self.plot:self.plot.deactivate()
        self.figure.clear()
        self.plot=si.GrainPlot(si.polygons_to_grains(self.result.polygons,self.image),image=self.image,
            predictor=predictor,figure=self.figure,blit=False,scale_m=.01)
        self.plot.events['button_press_event']=self.onpress
        self.plot.events['button_release_event']=self.onrelease
        self.plot.events['pick_event']=lambda event:self.plot.onpick(event) if self.mode.get()=='select' else None
        def onkey(event):
            if self.busy:return
            self.plot.onkey(event)
            if event.key in ('d','delete','m','z','c'):self.dirty=True
            self.update_labels()
        self.plot.events['key_press_event']=onkey
        self.plot.activate();self.canvas.draw()
        if session:
            self.length.set(str(session.get('reference_length',10)));self.unit.set(session.get('unit','mm'))
            if session.get('ruler_line'):
                self.plot.scale_m=self.reference_meters()
                p=np.asarray(session['ruler_line'])*self.plot.scale
                self.plot.draw_scale_line(p[0],p[1])
            self.dirty=False
        else:self.dirty=True
        self.update_labels();self.status.set(f'{len(self.plot.grains)} masks ready. Select masks, correct outlines, or calibrate the ruler.')

    def reference_meters(self):
        value=float(self.length.get())
        if not np.isfinite(value) or value<=0:raise ValueError('Ruler length must be a finite number greater than zero.')
        return value*{'mm':.001,'cm':.01}[self.unit.get()]

    def unit_changed(self,*args):
        if self.plot and self.plot.scale_line is not None:
            self.length.set(f'{self.plot.scale_m / {"mm":.001,"cm":.01}[self.unit.get()]:.8g}')
            self.dirty=True
        self.update_labels()

    def apply_scale(self):
        if not self.plot:return
        try:
            self.plot.scale_m=self.reference_meters()
            if self.plot.scale_line is not None:
                x,y=self.plot.scale_line.get_data();self.plot.draw_scale_line((x[0],y[0]),(x[-1],y[-1]));self.dirty=True
            self.update_labels()
        except ValueError as exc:messagebox.showerror('Ruler length',str(exc),parent=self.root)

    def onpress(self,event):
        if self.busy or event.inaxes!=self.plot.ax or self.toolbar.mode:return
        self.canvas.get_tk_widget().focus_set()
        mode=self.mode.get()
        if mode=='ruler' or event.key=='shift':
            try:self.plot.scale_m=self.reference_meters()
            except ValueError as exc:messagebox.showerror('Ruler length',str(exc),parent=self.root);return
            event.key='shift';self.plot.onclick(event)
        elif mode in ('foreground','background','add'):
            self.plot.clear_grains()
            self.plot.set_point((event.xdata,event.ydata),foreground=mode!='background')
            if mode=='add':self.create_mask()
            else:self.plot.update()

    def onrelease(self,event):
        if not self.plot:return
        drawing=self.plot.scale_drawing
        if drawing or event.key=='shift':self.plot.onclickup(event)
        if drawing:self.dirty=True
        self.update_labels()

    def create_mask(self):
        if not self.plot or self.busy:return
        try:
            with torch.no_grad():grain=self.plot.create_grain()
            if grain is not None:self.dirty=True
            self.plot.update();self.update_labels()
        except Exception as exc:messagebox.showerror('Mask creation',str(exc),parent=self.root)

    def action(self,name,dirty=True):
        if not self.plot or self.busy:return
        try:
            getattr(self.plot,name)();self.plot.update()
            if dirty:self.dirty=True
            self.update_labels()
        except Exception as exc:messagebox.showerror('Mask edit',str(exc),parent=self.root)

    def update_labels(self):
        if not self.plot:return
        self.count.set(f'{len(self.plot.grains)} masks · {len(self.plot.selected_grains)} selected')
        if self.plot.scale_line is None:self.scale_status.set('Not calibrated · export sizes in pixels')
        else:
            ppu=self.plot.px_per_m*{'mm':.001,'cm':.01}[self.unit.get()]
            self.scale_status.set(f'{ppu:.5g} pixels / {self.unit.get()}')
        self.sync_controls()
        if self.table_job:self.root.after_cancel(self.table_job)
        self.table_job=self.root.after(100,self.refresh_measurements)

    def sync_controls(self):
        for control,enabled in [(self.open_button,not self.busy),(self.project_button,not self.busy),
                                (self.run_button,self.image is not None and not self.busy),
                                (self.manual_button,self.image is not None and not self.busy),
                                (self.save_button,self.plot is not None and not self.busy),
                                (self.csv_button,self.plot is not None and not self.busy)]:
            control.state(['!disabled'] if enabled else ['disabled'])
        for control in self.edit_controls:
            control.state(['!disabled'] if self.plot is not None and not self.busy else ['disabled'])
        self.model_control.configure(state='disabled' if self.busy else 'readonly')
        self.area_control.configure(state='disabled' if self.busy else 'normal')

    def clear_measurements(self):
        if self.table_job:self.root.after_cancel(self.table_job);self.table_job=None
        self.table_data=None;self.table_key=None
        self.table.delete(*self.table.get_children());self.table.configure(displaycolumns='#all');self.table.configure(columns=())
        self.sort_column=None;self.sort_reverse=False
        self.table_status.set('Segment an image to see grain measurements here.')

    def current_measurements(self):
        ppm=self.plot.px_per_m if self.plot.scale_line is not None else None
        return self.result.measurement_table(self.plot.get_grains(),ppm,self.unit.get())

    def refresh_measurements(self):
        self.table_job=None
        if not self.plot:return
        grains=self.plot.get_grains()
        ppm=self.plot.px_per_m if self.plot.scale_line is not None else None
        key=(tuple(grains),ppm,self.unit.get())
        if key==self.table_key:return
        try:
            self.table_data=self.current_measurements();self.table_key=key
            units=self.unit.get() if ppm is not None else 'px'
            note=f'Sizes in {units}; areas in {units}²' if ppm is not None else 'Sizes in pixels · Draw a ruler reference for mm or cm'
            self.table_status.set(f'{len(self.table_data):,} grains · {note} · Same values as measurements.csv')
            self.render_measurements()
        except Exception as exc:
            self.table_key=None;self.table_data=None
            self.table.delete(*self.table.get_children())
            self.table_status.set(f'Measurements could not be calculated: {exc}')

    def render_measurements(self):
        data=self.table_data
        if data is None:return
        self.table.delete(*self.table.get_children())
        columns=['grain_row']+list(data.columns)
        self.table.configure(displaycolumns='#all');self.table.configure(columns=columns)
        primary=[c for prefix in ('area','major_axis_length','minor_axis_length','perimeter')
                 for c in data.columns if c==prefix or c.startswith(prefix+'_')]
        self.table.configure(displaycolumns=['grain_row']+primary+[c for c in data.columns if c not in primary])
        unit=self.unit.get() if self.plot.scale_line is not None else 'px'
        labels={'area':f'Area ({unit}²)','major_axis_length':f'Major axis ({unit})',
                'minor_axis_length':f'Minor axis ({unit})','perimeter':f'Perimeter ({unit})'}
        for col in columns:
            base=col
            for suffix in ('_mm2','_cm2','_mm','_cm'):
                if base.endswith(suffix):base=base[:-len(suffix)];break
            title='CSV row' if col=='grain_row' else labels.get(base,col.replace('_',' ').capitalize())
            if col==self.sort_column:title+=' ↓' if self.sort_reverse else ' ↑'
            self.table.heading(col,text=title,command=lambda c=col:self.sort_measurements(c))
            self.table.column(col,width=145 if col!='grain_row' else 75,minwidth=65,stretch=False,anchor='e')
        order=list(range(len(data)))
        if self.sort_column and self.sort_column!='grain_row' and self.sort_column in data:
            order=list(data.reset_index(drop=True).sort_values(self.sort_column,ascending=not self.sort_reverse,kind='stable',na_position='last').index)
        elif self.sort_column=='grain_row' and self.sort_reverse:order.reverse()
        for position,i in enumerate(order):
            values=[i+1]+[f'{v:.6g}' if isinstance(v,(float,np.floating)) else str(v) for v in data.iloc[i]]
            self.table.insert('', 'end',iid=str(i),values=values,tags=('alternate',) if position%2 else ())

    def sort_measurements(self,column):
        self.sort_reverse=not self.sort_reverse if self.sort_column==column else False
        self.sort_column=column;self.render_measurements()

    def export_csv(self):
        if self.busy or not self.plot:return
        path=filedialog.asksaveasfilename(title='Export grain measurements',initialfile='measurements.csv',defaultextension='.csv',filetypes=[('CSV table','*.csv')])
        if not path:return
        try:
            data=self.current_measurements();data.to_csv(path,index=False)
            self.refresh_measurements();self.status.set(f'Exported {len(data)} grain measurements to {path}')
        except Exception as exc:messagebox.showerror('Could not export CSV',str(exc),parent=self.root)

    def save(self):
        if self.busy or not self.plot:return
        folder=filedialog.askdirectory(title='Save project and results')
        if folder:self.save_to(folder)

    def save_to(self,folder):
        try:
            folder=Path(folder)
            calibrated=self.plot.scale_line is not None
            ppm=self.plot.px_per_m if calibrated else None
            self.result.save(folder,grains=self.plot.get_grains(),pixels_per_meter=ppm,unit=self.unit.get())
            Image.fromarray(self.image).save(folder/'image.png')
            ruler=None
            if calibrated:
                x,y=self.plot.scale_line.get_data();ruler=(np.array([[x[0],y[0]],[x[-1],y[-1]]])/self.plot.scale).tolist()
            session={'format_version':1,'variant':self.variant.get(),'unit':self.unit.get(),
                'reference_length':self.plot.scale_m / {'mm':.001,'cm':.01}[self.unit.get()] if calibrated else float(self.length.get()),'ruler_line':ruler}
            (folder/'project.json').write_text(json.dumps(session,indent=2))
            self.dirty=False;self.update_labels()
            self.status.set(f'Saved {len(self.plot.grains)} edited masks and {"calibrated" if calibrated else "pixel"} measurements to {folder}')
        except Exception as exc:messagebox.showerror('Could not save',str(exc),parent=self.root)

    def open_project(self):
        if self.busy or not self.unsaved_ok():return
        path=filedialog.askopenfilename(title='Open project.json',filetypes=[('Grain project','project.json')])
        if path:self.load_project(path)

    def load_project(self,path):
        try:
            folder=Path(path).parent;session=json.loads(Path(path).read_text())
            features=json.loads((folder/'grains.geojson').read_text())['features']
            from shapely.geometry import shape
            polygons=[shape(f['geometry']) for f in features]
            self.load_path(folder/'image.png');self.variant.set(session.get('variant','large'))
            image=self.image;variant=self.variant.get()
            def work():
                models=self.load_models(variant);predictor=SAM2ImagePredictor(models[1])
                with torch.no_grad():predictor.set_image(image)
                return SegmentationResult(image,polygons,None,models[1],models[2],0),predictor,session
            self.start_task('Loading project and interactive model…',work)
        except Exception as exc:messagebox.showerror('Could not open project',str(exc),parent=self.root)

    def setup(self):
        if self.busy or not self.unsaved_ok():return
        launcher=self.config.get('launcher')
        if launcher and Path(launcher).is_file():
            subprocess.Popen([launcher,'--setup'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.root.destroy()
        else:messagebox.showinfo('Machine setup','Run the Segment Every Grain setup application to change your configuration.',parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo('Working','Wait for the current operation to finish before closing.',parent=self.root);return
        if self.unsaved_ok():self.root.destroy()


def main():
    config=json.loads((APP_DIR/'config.json').read_text())
    root=tk.Tk();DesktopApp(root,config);root.update_idletasks()
    if os.environ.get('SEGMENTEVERYGRAIN_READY_FILE'):
        Path(os.environ['SEGMENTEVERYGRAIN_READY_FILE']).write_text(json.dumps({'ready':True}))
    root.mainloop()


if __name__=='__main__':main()
