"""Structured, throttled work progress; ETA is based on completed work, not a timer."""
import contextlib
import functools
import math
import time


class OperationProgress:
    def __init__(self, emit, clock=time.monotonic):
        self.emit=emit;self.clock=clock;self.last_sent=-math.inf;self.percent=0.
        self.message='Preparing…';self.low=0.;self.high=0.;self.started=clock()

    def stage(self, message, low, high, total=None):
        self.message=message;self.low=low;self.high=high;self.started=self.clock()
        self.update(0,total,force=True)

    def update(self, completed=0, total=None, force=False):
        now=self.clock()
        if not force and now-self.last_sent<.12 and completed!=total:return
        self.last_sent=now
        known=total is not None and total>0
        fraction=min(1.,max(0.,completed/total)) if known else 0.
        self.percent=max(self.percent,min(99.,self.low+(self.high-self.low)*fraction))
        elapsed=max(0.,now-self.started)
        remaining=(elapsed/completed)*(total-completed) if known and completed>0 and elapsed>=.5 else None
        self.emit({'event':'progress','message':self.message,'percent':self.percent,
                   'completed':completed if known else None,'total':total if known else None,
                   'remainingSeconds':remaining,'etaScope':'stage','indeterminate':not known})


@contextlib.contextmanager
def segmentation_progress(module, reporter, patch_count=1):
    """Observe existing pipeline calls and completed loop bodies, without changing inference.

    Patch only this isolated worker's module, and restore every hook on failure.
    Using the real ranges preserves SAM/U-Net work order and output exactly.
    """
    names=('predict_image','label_grains','sam_segmentation','find_connected_components',
           'merge_overlapping_polygons','create_labeled_image','_grain_properties_table','trange')
    original={name:getattr(module,name) for name in names}
    patch=-1;active='';bounds=(8.,91.)
    phases={
        'predict_image':('Scanning image tiles',0.,.16),
        'label_grains':('Locating grain prompts',.16,.20),
        'sam_segmentation':('Encoding image for mask detection',.20,.25),
        'find_connected_components':('Resolving overlapping masks',.84,.89),
        'merge_overlapping_polygons':('Refining grain boundaries',.89,.94),
        'create_labeled_image':('Building the grain label image',.94,.97),
        '_grain_properties_table':('Calculating grain properties',.97,1.),
    }

    def stage(message,low,high,total=None):
        start,end=bounds;span=end-start
        prefix=f'Patch {patch+1}/{patch_count} · ' if patch_count>1 else ''
        reporter.stage(prefix+message,start+span*low,start+span*high,total)

    def wrap(name):
        @functools.wraps(original[name])
        def call(*args,**kwargs):
            nonlocal patch,active,bounds
            # Proposal generation also measures provisional labels; it is not
            # the final measurement phase of the SAM pipeline.
            if name=='_grain_properties_table' and active=='label_grains':
                return original[name](*args,**kwargs)
            previous=active;active=name
            if name=='predict_image':
                patch+=1;bounds=(8+83*patch/patch_count,8+83*(patch+1)/patch_count)
            message,low,high=phases[name];stage(message,low,high)
            try:
                value=original[name](*args,**kwargs)
                completed_high=1. if name=='sam_segmentation' else high
                stage(message,completed_high,completed_high,1);reporter.update(1,1,force=True)
                return value
            finally:active=previous
        return call

    def tracked_range(*args,**kwargs):
        work=range(*args);total=len(work)
        if active=='predict_image':stage('Scanning image tiles',0.,.16,total)
        elif active=='sam_segmentation':stage('Detecting grain masks',.25,.84,total)
        else:
            # Other loops retain the enclosing phase's bounds and message.
            reporter.started=reporter.clock();reporter.update(0,total,force=True)
        for completed,item in enumerate(work,1):
            yield item
            reporter.update(completed,total)

    try:
        for name in names:
            setattr(module,name,tracked_range if name=='trange' else wrap(name))
        yield
    finally:
        for name,value in original.items():setattr(module,name,value)
