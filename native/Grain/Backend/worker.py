"""Local JSON-lines worker. No UI toolkit or network listener is used.

stdout is exclusively protocol; model logs/progress are redirected to stderr.
One request is processed at a time. Native UI remains responsive independently.
"""
import sys
import json
import os
from pathlib import Path
import traceback
import tempfile
import time
import math
import importlib.util

# Resolve the sibling module explicitly: tests and embedded launches need not
# place this folder on sys.path, and a third-party package may also be named progress.
_progress_spec=importlib.util.spec_from_file_location('grain_work_progress',Path(__file__).with_name('progress.py'))
_progress=importlib.util.module_from_spec(_progress_spec);_progress_spec.loader.exec_module(_progress)
OperationProgress=_progress.OperationProgress
segmentation_progress=_progress.segmentation_progress

PROTOCOL = sys.stdout
sys.stdout = sys.stderr
os.environ.setdefault('MPLBACKEND', 'Agg')


def emit(data):
    PROTOCOL.write(json.dumps(data, allow_nan=False, separators=(',', ':'))+'\n')
    PROTOCOL.flush()


class Workspace:
    def __init__(self):
        import numpy as np
        from PIL import Image
        from shapely.geometry import Polygon, shape
        from segmenteverygrain.inference import SegmentationResult
        from segmenteverygrain import interactions
        self.np=np;self.Image=Image;self.Polygon=Polygon;self.shape=shape
        self.Result=SegmentationResult;self.si=interactions
        app=Path(os.environ['LOCALAPPDATA'])/'SegmentEveryGrainDesktop'
        self.config=json.loads((app/'config.json').read_text())
        self.image=None;self.path=None;self.grains=[];self.next_id=1
        self.ppm=None;self.ruler=None;self.unit='mm';self.reference=10.
        self.variant=self.config.get('variant','large');self.backend=self.config.get('backend','cpu')
        self.models=None;self.model_key=None;self.predictor=None;self.seconds=0
        self.undo=[];self.redo=[];self.revision=0;self.saved_revision=0;self.project=None
        self.cache=tempfile.TemporaryDirectory(prefix='grain-winui-')
        self.preview=None;self.image_revision=0
        self.progress=None

    def stage(self,message,low,high,total=None):
        if self.progress:self.progress.stage(message,low,high,total)

    def advanced(self,completed,total):
        if self.progress:self.progress.update(completed,total)

    def remember(self):
        return (list(self.grains),self.next_id,self.ppm,self.ruler,self.unit,self.reference,self.revision)

    def checkpoint(self):
        self.undo.append(self.remember());self.undo=self.undo[-60:];self.redo=[]
        self.revision=time.time_ns()

    def restore(self,state):
        self.grains,self.next_id,self.ppm,self.ruler,self.unit,self.reference,self.revision=state

    def assign(self,polygons,ids=None):
        self.grains=[]
        self.stage('Measuring individual grains',91,96,len(polygons))
        for i,p in enumerate(polygons):
            if p.is_empty or p.area<=0:continue
            if p.geom_type!='Polygon':continue
            grain=self.si.Grain(p.exterior.xy,self.image)
            grain.measure()
            self.grains.append((int(ids[i]) if ids else i+1,grain))
            self.advanced(i+1,len(polygons))
        self.next_id=max((i for i,g in self.grains),default=0)+1

    def load_image(self,path):
        self.stage('Reading image',0,40)
        path=Path(path)
        with self.Image.open(path) as im:image=self.np.array(im.convert('RGB'))
        self.image=image;self.path=path;self.grains=[];self.next_id=1
        self.ppm=None;self.ruler=None;self.unit='mm';self.reference=10.
        self.predictor=None;self.undo=[];self.redo=[];self.revision=0;self.saved_revision=0;self.project=None
        self.image_revision+=1
        self.preview=str(Path(self.cache.name)/f'image-{self.image_revision}.png')
        self.stage('Preparing image preview',40,70)
        self.Image.fromarray(image).save(self.preview)

    def ensure_models(self):
        import torch
        from sam2.build_sam import build_sam2
        from segmenteverygrain.directml import get_device,sam_checkpoint_path
        from segmenteverygrain.unet import load_unet
        key=(self.variant,self.backend)
        if key!=self.model_key:
            self.stage('Loading segmentation models',0,8)
            device=get_device(self.config.get('adapter_name','RX 6600')) if self.backend=='directml' else torch.device('cpu')
            import segmenteverygrain
            unet=load_unet(str(Path(segmenteverygrain.__file__).parent/'models/seg_model_smooth_labels.pt'),device=device)
            sam=build_sam2(f'configs/sam2.1/sam2.1_hiera_{"l" if self.variant=="large" else "t"}.yaml',str(sam_checkpoint_path(self.variant)),device=device)
            self.models=(unet,sam,device);self.model_key=key;self.predictor=None
        return self.models

    def table(self):
        import pandas as pd
        current=[g for i,g in self.grains]
        for grain in current:
            if grain.data is None:grain.measure()
        factor=self.ppm*{'mm':.001,'cm':.01}[self.unit] if self.ppm is not None else 1.
        data=self.si.get_summary(current,px_per_m=factor) if current else pd.DataFrame(columns=['area','major_axis_length','minor_axis_length','perimeter'])
        if self.ppm is not None:
            names={k:f'{k}_{self.unit}' for k in ('major_axis_length','minor_axis_length','perimeter')}
            names['area']=f'area_{self.unit}2';data=data.rename(columns=names)
        data.insert(0,'grain_id',[i for i,g in self.grains])
        return data

    def state(self):
        if self.image is None:return {'loaded':False,'config':self.config}
        self.stage('Preparing measurement table',96,97)
        data=self.table()
        records=json.loads(data.to_json(orient='records',double_precision=12))
        grains=[]
        self.stage('Preparing grain overlays',97,98,len(self.grains))
        for completed,((i,g),values) in enumerate(zip(self.grains,records),1):
            p=g.polygon
            # Display simplification only; measurements and exports retain full geometry.
            display=p.simplify(.3,preserve_topology=True)
            rings=[list(map(list,display.exterior.coords))]+[list(map(list,r.coords)) for r in display.interiors]
            grains.append({'id':i,'rings':rings,'values':values})
            self.advanced(completed,len(self.grains))
        return {'loaded':True,'imagePath':self.preview,'sourcePath':str(self.path),'width':self.image.shape[1],
                'geometryToken':str(hash(tuple((i,id(g)) for i,g in self.grains))),
                'height':self.image.shape[0],'columns':list(data.columns),'grains':grains,
                'unit':self.unit if self.ppm is not None else 'px','calibrationUnit':self.unit,
                'pixelsPerMeter':self.ppm,'ruler':self.ruler,'referenceLength':self.reference,
                'canUndo':bool(self.undo),'canRedo':bool(self.redo),'dirty':self.revision!=self.saved_revision,
                'variant':self.variant,'backend':self.backend,'seconds':self.seconds,'project':self.project,
                'config':self.config}

    def execute(self,method,args):
        """Keep a failed request from replacing the active in-memory project."""
        original=self.remember()
        self.progress=OperationProgress(emit)
        titles={'hello':'Connecting to the processing engine','open':'Opening image','open_project':'Reading saved project',
                'segment':'Preparing segmentation','manual':'Preparing manual editor','add':'Preparing mask prediction',
                'delete':'Removing selected grains','merge':'Merging selected grains','calibrate':'Updating ruler calibration',
                'clear_calibration':'Restoring pixel measurements','undo':'Restoring previous edit','redo':'Restoring next edit',
                'export':'Writing measurement CSV','save':'Preparing project files'}
        self.stage(titles.get(method,'Processing'),0,90)
        metadata=(self.image,self.path,self.preview,self.image_revision,self.project,self.predictor,self.seconds,self.variant,self.backend,self.saved_revision,list(self.undo),list(self.redo))
        try:return self._execute(method,args)
        except Exception:
            self.restore(original)
            (self.image,self.path,self.preview,self.image_revision,self.project,self.predictor,self.seconds,self.variant,self.backend,self.saved_revision,self.undo,self.redo)=metadata
            raise
        finally:self.progress=None

    def _execute(self,method,args):
        if method=='hello':return self.state()
        if method=='open':
            self.load_image(args['path']);return self.state()
        if method=='open_project':
            path=Path(args['path']);folder=path.parent
            session=json.loads(path.read_text())
            features=json.loads((folder/'grains.geojson').read_text())['features']
            polygons=[self.shape(f['geometry']) for f in features]
            with self.Image.open(folder/'image.png') as im:im.verify()
            self.load_image(folder/'image.png')
            self.assign(polygons,[f.get('properties',{}).get('grain_id',i+1) for i,f in enumerate(features)])
            self.variant=session.get('variant','large');self.unit=session.get('unit','mm')
            self.reference=float(session.get('reference_length',10));self.ruler=session.get('ruler_line')
            if self.ruler:
                self.ppm=math.dist(*self.ruler)/(self.reference*{'mm':.001,'cm':.01}[self.unit])
            self.project=str(folder)
            return self.state()
        if self.image is None:raise ValueError('Open an image first.')
        if method=='segment':
            from segmenteverygrain.inference import segment_image
            import torch
            variant=args.get('variant',self.variant);backend=args.get('backend',self.backend)
            if variant not in ('large','tiny') or backend not in ('cpu','directml'):raise ValueError('Invalid model or device.')
            minimum=int(args.get('minimum',50))
            if minimum<1:raise ValueError('Minimum area must be a positive whole number.')
            self.variant=variant;self.backend=backend
            models=self.ensure_models();started=time.perf_counter()
            from segmenteverygrain import segmenteverygrain as pipeline
            large=max(self.image.shape[:2])>2200
            patches=(max(1,(self.image.shape[0]-2000+1700)//1700+1)*
                     max(1,(self.image.shape[1]-2000+1700)//1700+1)) if large else 1
            with segmentation_progress(pipeline,self.progress,patches):
                if large:
                    with torch.no_grad():
                        polygons,_,_=pipeline.predict_large_image(str(self.path),models[0],sam=models[1],min_area=minimum,
                            patch_size=2000,overlap=300,remove_edge_grains=False,verbose=False)
                else:polygons=segment_image(self.image,models=models,min_area=minimum).polygons
            self.checkpoint();self.assign(polygons);self.seconds=time.perf_counter()-started
            self.predictor=None
        elif method=='manual':
            self.variant=args.get('variant',self.variant);self.backend=args.get('backend',self.backend)
            if self.variant not in ('large','tiny') or self.backend not in ('cpu','directml'):raise ValueError('Invalid model or device.')
            self.checkpoint();self.grains=[];self.next_id=1
        elif method=='add':
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            import torch
            points=args.get('points',[]);labels=args.get('labels',[])
            if not points or len(points)!=len(labels) or not any(labels):raise ValueError('Place at least one foreground point inside a grain.')
            for x,y in points:
                if not (math.isfinite(x) and math.isfinite(y) and 0<=x<self.image.shape[1] and 0<=y<self.image.shape[0]):raise ValueError('Prompt points must be inside the image.')
            self.variant=args.get('variant',self.variant);self.backend=args.get('backend',self.backend)
            if self.variant not in ('large','tiny') or self.backend not in ('cpu','directml'):raise ValueError('Invalid model or device.')
            models=self.ensure_models()
            with torch.no_grad():
                if self.predictor is None:
                    self.stage('Encoding image for interactive masks',8,55)
                    self.predictor=SAM2ImagePredictor(models[1]);self.predictor.set_image(self.image)
                self.stage('Predicting mask from your points',55,85)
                sx,sy=self.si.predict_from_prompts(self.predictor,points=points,point_labels=labels)
            if sx is None:raise ValueError('No boundary was found. Try adding more foreground and background points.')
            polygon=self.Polygon(zip(sx,sy))
            if not polygon.is_valid:polygon=polygon.buffer(0)
            if polygon.geom_type!='Polygon' or polygon.area<=0:raise ValueError('The mask is not one valid grain. Adjust the prompt points.')
            grain=self.si.Grain(polygon.exterior.xy,self.image);grain.measure()
            self.checkpoint();self.grains.append((self.next_id,grain));self.next_id+=1
        elif method in ('delete','merge'):
            selected=set(args.get('ids',[]));current=[g for i,g in self.grains if i in selected]
            if not current:raise ValueError('Select grains in the image or table first.')
            grain=None
            if method=='merge':
                from shapely import unary_union
                if len(current)<2:raise ValueError('Select at least two touching grains to merge.')
                polygon=unary_union([g.polygon for g in current])
                if polygon.geom_type!='Polygon':raise ValueError('Only touching or overlapping grains can be merged.')
                grain=self.si.Grain(polygon.exterior.xy,self.image);grain.measure()
            self.checkpoint();self.grains=[(i,g) for i,g in self.grains if i not in selected]
            if grain:self.grains.append((self.next_id,grain));self.next_id+=1
        elif method=='calibrate':
            points=args.get('points',self.ruler);length=float(args['length']);unit=args['unit']
            if unit not in ('mm','cm') or not math.isfinite(length) or length<=0:raise ValueError('Enter a positive ruler length in mm or cm.')
            if not points or len(points)!=2 or not all(math.isfinite(v) for p in points for v in p) or math.dist(*points)<2:raise ValueError('Draw a reference at least two pixels long.')
            ppm=math.dist(*points)/(length*{'mm':.001,'cm':.01}[unit])
            self.checkpoint();self.ruler=points;self.reference=length;self.unit=unit;self.ppm=ppm
        elif method=='clear_calibration':
            self.checkpoint();self.ruler=None;self.ppm=None
        elif method in ('undo','redo'):
            source,target=(self.undo,self.redo) if method=='undo' else (self.redo,self.undo)
            if source:
                target.append(self.remember());self.restore(source.pop())
        elif method=='export':
            self.table().to_csv(args['path'],index=False)
        elif method=='save':
            folder=Path(args['path']);folder.mkdir(parents=True,exist_ok=True)
            result=self.Result(self.image,[],None,None,self.backend,self.seconds)
            self.stage('Writing outlines and training mask',5,65)
            result.save(folder,grains=[g for i,g in self.grains],pixels_per_meter=self.ppm,unit=self.unit)
            self.stage('Writing measurement CSV',65,75)
            self.table().to_csv(folder/'measurements.csv',index=False)
            run=json.loads((folder/'run.json').read_text());run['measurement_unit']=self.unit if self.ppm is not None else 'pixels'
            (folder/'run.json').write_text(json.dumps(run,indent=2))
            geo=json.loads((folder/'grains.geojson').read_text())
            for feature,(i,g) in zip(geo['features'],self.grains):feature.setdefault('properties',{})['grain_id']=i
            (folder/'grains.geojson').write_text(json.dumps(geo))
            self.stage('Saving original image',75,90)
            self.Image.fromarray(self.image).save(folder/'image.png')
            self.stage('Saving project settings',90,96)
            (folder/'project.json').write_text(json.dumps({'format_version':2,'variant':self.variant,'unit':self.unit,
                'reference_length':self.reference,'ruler_line':self.ruler,'ui':'winui3'},indent=2))
            self.project=str(folder);self.saved_revision=self.revision
        else:raise ValueError(f'Unknown operation: {method}')
        return self.state()


def main():
    emit({'event':'progress','message':'Starting the local processing engine…','indeterminate':True})
    try:workspace=Workspace();emit({'event':'ready'})
    except Exception:
        emit({'event':'fatal','message':traceback.format_exc()});return
    for line in sys.stdin:
        request=None
        try:
            request=json.loads(line)
            result=workspace.execute(request['method'],request.get('args',{}))
            emit({'id':request['id'],'result':result})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            emit({'id':request.get('id',-1) if request else -1,'error':str(exc)})
    workspace.cache.cleanup()


if __name__=='__main__':main()
