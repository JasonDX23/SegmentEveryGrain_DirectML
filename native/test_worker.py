"""Functional tests for the actual native application's worker, not a mock."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import argparse
import numpy as np
import pandas as pd
from PIL import Image
from shapely.geometry import box

spec=importlib.util.spec_from_file_location('grain_worker',Path(__file__).parent/'Grain/Backend/worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)


def check(gpu=False,image_path=None):
    events=[];worker.emit=events.append
    workspace=worker.Workspace()
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);image=tmp/'test.png';Image.fromarray(np.full((240,360,3),150,dtype=np.uint8)).save(image)
        workspace.execute('open',{'path':str(image)})
        workspace.assign([box(20,20,60,40),box(60,20,100,40)])
        original=workspace.table().copy(deep=True)
        assert original['area'].tolist()==[800,800]
        workspace.execute('calibrate',{'points':[[20,200],[120,200]],'length':10,'unit':'mm'})
        assert np.isclose(workspace.table().iloc[0]['area_mm2'],8)
        workspace.execute('calibrate',{'length':1,'unit':'cm'})
        assert np.isclose(workspace.table().iloc[0]['area_cm2'],.08)
        project=tmp/'project';workspace.execute('save',{'path':str(project)})
        pd.testing.assert_frame_equal(pd.read_csv(project/'measurements.csv'),workspace.table(),check_dtype=False,check_index_type=False)
        assert not workspace.state()['dirty']
        workspace.execute('delete',{'ids':[1]});assert len(workspace.grains)==1
        assert workspace.state()['dirty']
        workspace.execute('undo',{});assert len(workspace.grains)==2;assert not workspace.state()['dirty']
        workspace.execute('redo',{});assert len(workspace.grains)==1
        workspace.execute('undo',{})
        workspace.execute('merge',{'ids':[1,2]});assert len(workspace.grains)==1
        assert np.isclose(workspace.table().iloc[0]['area_cm2'],.16)
        workspace.execute('undo',{})
        workspace.execute('open_project',{'path':str(project/'project.json')})
        assert [i for i,g in workspace.grains]==[1,2]
        assert np.isclose(workspace.table().iloc[0]['area_cm2'],.08)
        workspace.execute('export',{'path':str(tmp/'standalone.csv')})
        pd.testing.assert_frame_equal(pd.read_csv(tmp/'standalone.csv'),workspace.table(),check_dtype=False,check_index_type=False)
        workspace.execute('manual',{});assert not workspace.grains
        workspace.execute('save',{'path':str(tmp/'empty')})
        assert 'area_cm2' in pd.read_csv(tmp/'empty/measurements.csv').columns
        assert json.loads((tmp/'empty/run.json').read_text())['measurement_unit']=='cm'
        workspace.execute('undo',{});assert len(workspace.grains)==2
        # Invalid edits preserve the existing state.
        before=workspace.remember()
        for method,args in [('calibrate',{'points':[[0,0],[1,1]],'length':10,'unit':'mm'}),('merge',{'ids':[1]}),('add',{'points':[],'labels':[]})]:
            try:workspace.execute(method,args)
            except ValueError:pass
            else:raise AssertionError('Expected a validation error')
            assert workspace.remember()==before
        workspace.execute('clear_calibration',{});assert 'area' in workspace.table().columns
        # A malformed project may fail after reading its image; the old workspace survives.
        broken=tmp/'broken';broken.mkdir();Image.fromarray(np.zeros((50,50,3),dtype=np.uint8)).save(broken/'image.png')
        (broken/'grains.geojson').write_text(json.dumps({'features':[]}))
        (broken/'project.json').write_text(json.dumps({'unit':'invalid','reference_length':1,'ruler_line':[[0,0],[10,0]]}))
        before_image=workspace.image;before_state=workspace.remember()
        try:workspace.execute('open_project',{'path':str(broken/'project.json')})
        except KeyError:pass
        else:raise AssertionError('Malformed calibration should fail')
        assert workspace.image is before_image and workspace.remember()==before_state
        assert 'tkinter' not in sys.modules
        if gpu:
            workspace.execute('open',{'path':str(Path(image_path).resolve())})
            events.clear()
            state=workspace.execute('segment',{'variant':'large','backend':'directml','minimum':50})
            assert len(state['grains'])>100
            segmentation_events=list(events)
            percentages=[event['percent'] for event in segmentation_events]
            assert len(segmentation_events)>20 and percentages==sorted(percentages)
            assert any(e['remainingSeconds'] is not None and e['remainingSeconds']>0 for e in segmentation_events)
            assert any('Detecting grain masks' in e['message'] and e['completed']==e['total'] and e['total']>0 for e in segmentation_events)
            mask_events=[e for e in segmentation_events if 'Detecting grain masks' in e['message']]
            assert mask_events[-1]['percent']-mask_events[0]['percent']>30
            first=workspace.grains[0][1].polygon.centroid
            state=workspace.execute('add',{'points':[[first.x,first.y]],'labels':[1]})
            assert len(state['grains'])>100
            out=Path(__file__).resolve().parent.parent/'verification/native-gpu-project'
            workspace.execute('save',{'path':str(out)})
            pd.testing.assert_frame_equal(pd.read_csv(out/'measurements.csv'),workspace.table(),check_dtype=False,check_index_type=False)
            (out.parent/'native-gpu.json').write_text(json.dumps({'passed':True,'grain_count':len(state['grains']),'backend':'directml','one_click_add':True,'csv_parity':True,
                'progress_events':len(segmentation_events),'monotonic_progress':True,'measured_stage_eta':True},indent=2))
            (out.parent/'native-progress-events.json').write_text(json.dumps(segmentation_events,indent=2))
    workspace.cache.cleanup()
    print('PASS: native worker calibration, stable IDs, CSV parity, deletion, merge, undo/redo, dirty state, project reopening, empty export and invalid edits',file=sys.stderr)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpu',action='store_true',help='Also exercise DirectML inference and measured progress on a grain-rich image.')
    parser.add_argument('--image',type=Path,help='Local sample image for the GPU integration test.')
    options=parser.parse_args()
    if options.gpu and (options.image is None or not options.image.is_file()):
        parser.error('--gpu requires --image pointing to an existing grain-rich image.')
    check(gpu=options.gpu,image_path=options.image)
