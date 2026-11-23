"""Image inference and result export without a notebook server."""
from dataclasses import dataclass
from pathlib import Path
import json
import time
import numpy as np
import torch
from PIL import Image
from .directml import load_models


@dataclass
class SegmentationResult:
    image: np.ndarray
    polygons: list
    measurements: object
    sam: object
    device: object
    seconds: float

    def measurement_table(self, grains=None, pixels_per_meter=None, unit='mm'):
        """Return the exact export table without writing any files."""
        from . import interactions as si
        import pandas as pd
        current = si.polygons_to_grains(self.polygons,self.image) if grains is None else grains
        if pixels_per_meter is not None:
            if not np.isfinite(pixels_per_meter) or pixels_per_meter <= 0 or unit not in ('mm','cm'):
                raise ValueError('Use a positive pixels_per_meter and unit mm or cm')
        for grain in current:
            if grain.data is None:
                grain.measure()
        data = (si.get_summary(current, px_per_m=pixels_per_meter * {'mm':.001,'cm':.01}[unit]
                               if pixels_per_meter is not None else 1.)
                if current else pd.DataFrame(columns=['area','major_axis_length','minor_axis_length','perimeter']))
        if pixels_per_meter is not None:
            names={k:f'{k}_{unit}' for k in ('major_axis_length','minor_axis_length','perimeter')}
            names['area']=f'area_{unit}2'
            data=data.rename(columns=names)
        return data

    def save(self, directory, grains=None, pixels_per_meter=None, unit='mm'):
        """Export current polygons, semantic mask, measurements, and calibration.

        Without calibration measurements use pixels. GeoJSON always uses pixels.
        """
        from . import interactions as si
        folder=Path(directory); folder.mkdir(parents=True,exist_ok=True)
        current = si.polygons_to_grains(self.polygons,self.image) if grains is None else grains
        data=self.measurement_table(current,pixels_per_meter,unit)
        if not current:
            data.to_csv(folder/'measurements.csv',index=False)
            (folder/'grains.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[]}))
            Image.fromarray(np.zeros(self.image.shape[:2],dtype=np.uint8)).save(folder/'mask.png')
            (folder/'run.json').write_text(json.dumps({'device':str(self.device),'grain_count':0,
                'segmentation_seconds':self.seconds,'measurement_unit':unit if pixels_per_meter is not None else 'pixels',
                'pixels_per_meter':pixels_per_meter,'coordinate_unit':'pixels'},indent=2))
            return data
        if pixels_per_meter is None:unit='pixels'
        data.to_csv(folder/'measurements.csv',index=False)
        si.save_grains(str(folder/'grains.geojson'),current)
        si.save_mask(str(folder/'mask.png'),current,self.image)
        (folder/'run.json').write_text(json.dumps({'device':str(self.device),'grain_count':len(current),
            'segmentation_seconds':self.seconds,'measurement_unit':unit,
            'pixels_per_meter':pixels_per_meter,'coordinate_unit':'pixels'},indent=2))
        return data


def segment_image(image, variant='large', models=None, batch_size=8, min_area=50):
    """Segment an image path, PIL image, or RGB uint8 array on RX 6600.

    Reuse ``models=load_models()`` across images to avoid reloading weights.
    Returns a SegmentationResult; use result.save(...) or edit_result(result).
    """
    from .segmenteverygrain import predict_image,label_grains,sam_segmentation
    if isinstance(image,(str,Path)):
        with Image.open(image) as loaded:
            image=np.array(loaded.convert('RGB'))
    elif isinstance(image,Image.Image):
        image=np.array(image.convert('RGB'))
    image=np.asarray(image)
    if image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8:
        raise ValueError('Expected an RGB uint8 image array')
    unet,sam,device = load_models(variant=variant) if models is None else models
    started=time.perf_counter()
    with torch.no_grad():
        prediction=predict_image(image,unet,256,batch_size=batch_size)
        labels,coords=label_grains(image,prediction)
        polygons,_,_,data,_,_=sam_segmentation(sam,image,prediction,coords,labels,
            min_area=min_area,plot_image=False,remove_edge_grains=False)
    return SegmentationResult(image,polygons,data,sam,device,time.perf_counter()-started)


def edit_result(result, output_dir='grain_results'):
    """Open the original mask editor in a native Tk window, without Jupyter."""
    import matplotlib
    matplotlib.use('TkAgg',force=True)
    from matplotlib import pyplot as plt
    import tkinter as tk
    from tkinter import ttk,messagebox
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    from . import interactions as si
    predictor=SAM2ImagePredictor(result.sam)
    with torch.no_grad(): predictor.set_image(result.image)
    plot=si.GrainPlot(si.polygons_to_grains(result.polygons,result.image),
        image=result.image,predictor=predictor,blit=False,figsize=(11,8),scale_m=.01)
    plot.activate()
    window=plot.canvas.manager.window
    window.title('Segment every grain — RX 6600')
    controls=ttk.Frame(window);controls.pack(side=tk.TOP,fill=tk.X,before=plot.canvas.get_tk_widget())
    length=tk.StringVar(value='10');unit=tk.StringVar(value='mm');status=tk.StringVar(value='Enter ruler length, then Shift-drag across that ruler interval.')
    ttk.Label(controls,text='Ruler length:').pack(side=tk.LEFT)
    ttk.Entry(controls,textvariable=length,width=8).pack(side=tk.LEFT)
    ttk.Combobox(controls,textvariable=unit,values=['mm','cm'],state='readonly',width=5).pack(side=tk.LEFT)

    def calibrate(redraw=True):
        value=float(length.get())
        if value<=0: raise ValueError('Ruler length must be positive')
        plot.scale_m=value*{'mm':.001,'cm':.01}[unit.get()]
        if redraw and plot.scale_line is not None:
            x,y=plot.scale_line.get_data();plot.draw_scale_line((x[0],y[0]),(x[-1],y[-1]))
        if plot.scale_line is not None:
            status.set(f'{plot.px_per_m*{"mm":.001,"cm":.01}[unit.get()]:.4g} pixels/{unit.get()}')

    def apply():
        try: calibrate()
        except ValueError as exc: messagebox.showerror('Calibration',str(exc),parent=window)

    def before_draw(event):
        if event.key=='shift' and event.button==1:
            try: calibrate(False)
            except ValueError: pass

    def save():
        try:
            calibrate()
            if plot.scale_line is None: raise ValueError('Shift-drag a ruler reference before saving calibrated measurements')
            data=result.save(output_dir,grains=plot.get_grains(),pixels_per_meter=plot.px_per_m,unit=unit.get())
            result.polygons=[g.polygon for g in plot.get_grains()]
            status.set(f'Saved {len(data)} edited grains to {Path(output_dir).resolve()}')
        except (ValueError,OSError) as exc: messagebox.showerror('Export',str(exc),parent=window)

    ttk.Button(controls,text='Apply ruler length',command=apply).pack(side=tk.LEFT,padx=5)
    ttk.Button(controls,text='Save edited results',command=save).pack(side=tk.LEFT,padx=5)
    ttk.Label(window,textvariable=status).pack(side=tk.BOTTOM,fill=tk.X)
    ttk.Label(window,text='Shift-drag: ruler | Click: select/add | d: delete | m: merge | Alt+click: foreground | Alt+right-click: background | Esc: clear').pack(side=tk.BOTTOM,fill=tk.X)
    plot.canvas.mpl_connect('button_press_event',before_draw)
    plot.canvas.mpl_connect('button_release_event',lambda event: calibrate() if plot.scale_line is not None else None)
    plt.show(block=True)
    plot.deactivate()
    return result
