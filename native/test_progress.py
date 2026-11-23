"""Verify progress counts, stage ETA, patch accounting and hook cleanup."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('work_progress_test',Path(__file__).parent/'Grain/Backend/progress.py')
progress=importlib.util.module_from_spec(spec);spec.loader.exec_module(progress)


def check():
    now=[0.];events=[]
    reporter=progress.OperationProgress(events.append,clock=lambda:now[0])
    reporter.stage('Measured work',10,60,10)
    now[0]=2;reporter.update(2,10)
    assert events[-1]['percent']==20
    assert events[-1]['remainingSeconds']==8
    assert events[-1]['etaScope']=='stage'
    reporter.stage('Unknown duration',60,80)
    assert events[-1]['indeterminate'] and events[-1]['remainingSeconds'] is None
    reporter.stage('Next work',5,10,1);now[0]+=1;reporter.update(1,1)
    assert events[-1]['percent']>=60

    events.clear();reporter=progress.OperationProgress(events.append,clock=lambda:now[0])
    module=SimpleNamespace(trange=lambda *args,**kwargs:range(*args))
    def scan():
        for _ in module.trange(0,12,3,desc='tiles'):now[0]+=.5
        return 'same prediction'
    def noop():return None
    def masks(fail=False):
        for i in module.trange(8):
            now[0]+=.2
            if fail and i==3:raise RuntimeError('deliberate test failure')
        module.find_connected_components();module.merge_overlapping_polygons()
        module.create_labeled_image();module._grain_properties_table()
        return 'same masks'
    def label():module._grain_properties_table()
    module.predict_image=scan;module.label_grains=label;module.sam_segmentation=masks
    for name in ('find_connected_components','merge_overlapping_polygons','create_labeled_image','_grain_properties_table'):setattr(module,name,noop)
    original=dict(vars(module))
    with progress.segmentation_progress(module,reporter,patch_count=2):
        for _ in range(2):
            assert module.predict_image()=='same prediction'
            module.label_grains()
            assert reporter.percent<83
            assert module.sam_segmentation()=='same masks'
    assert all(getattr(module,k) is v for k,v in original.items())
    values=[e['percent'] for e in events]
    assert values==sorted(values) and values[-1]==91
    assert any(e['message'].startswith('Patch 2/2') for e in events)
    assert any(e['total']==4 and e['completed']==4 for e in events)
    assert any(e['total']==8 and e['completed']==8 for e in events)
    assert any(e['remainingSeconds'] is not None and e['remainingSeconds']>0 for e in events)
    try:
        with progress.segmentation_progress(module,reporter):
            module.predict_image();module.sam_segmentation(fail=True)
    except RuntimeError:pass
    else:raise AssertionError('Test error must propagate')
    assert all(getattr(module,k) is v for k,v in original.items())
    print('PASS: measured ETA, unknown phases, monotonic work progress, batching, multiple patches and hook restoration')


if __name__=='__main__':check()
