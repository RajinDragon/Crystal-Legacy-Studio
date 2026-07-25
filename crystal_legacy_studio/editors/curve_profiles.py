from dataclasses import dataclass
import math
CURVE_TYPES=("Linear","Front Loaded","Back Loaded","Late Start","Early Burst","S Curve","Exponential","Logarithmic")
@dataclass(frozen=True)
class CurveRequest:
    start_level:int; end_level:int; base_value:int; target_value:int; curve_type:str="Linear"; slope:float=1.0; late_start:int=1

def _shape(x,kind,slope,late_ratio):
    x=min(1,max(0,x)); slope=max(.15,min(6.0,slope))
    if kind=="Front Loaded": return 1-(1-x)**slope
    if kind=="Back Loaded": return x**slope
    if kind=="Late Start":
        if x<=late_ratio:return 0.0
        return ((x-late_ratio)/max(1e-9,1-late_ratio))**slope
    if kind=="Early Burst": return min(1.0,(x*2.0)**(1.0/slope))
    if kind=="S Curve":
        k=7*slope; raw=1/(1+math.exp(-k*(x-.5))); lo=1/(1+math.exp(k*.5)); hi=1/(1+math.exp(-k*.5)); return (raw-lo)/(hi-lo)
    if kind=="Exponential": return (math.exp(slope*x)-1)/(math.exp(slope)-1)
    if kind=="Logarithmic": return math.log1p(slope*x)/math.log1p(slope)
    return x

def generate_curve(req):
    levels=list(range(req.start_level,req.end_level+1)); gain=max(0,req.target_value-req.base_value)
    if not levels:return {}
    if gain==0:return {l:0 for l in levels}
    span=max(1,req.end_level-req.start_level); late=(max(req.start_level,req.late_start)-req.start_level)/span
    cumulative=[_shape((l-req.start_level)/span,req.curve_type,req.slope,late) for l in levels]
    scaled=[round(v*gain) for v in cumulative]; scaled[0]=0; scaled[-1]=gain
    out={}; prev=0
    for l,v in zip(levels,scaled): out[l]=max(0,v-prev); prev=v
    out[levels[-1]] += gain-sum(out.values())
    return out

def calculate_final(base,increments): return base+sum(increments.values())
