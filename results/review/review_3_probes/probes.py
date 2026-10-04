import sys, math, json, itertools
from pathlib import Path
R=Path('<repo>'); sys.path.insert(0,str(R))
from phoenix_evidence._canary import log_evidence,canary,count_flips
from phoenix_evidence._price import _human_width,_smallest,price_of_certainty
from phoenix_evidence._jury import jury
from phoenix_evidence._doctor import pair_accuracy,diagnose,Example
from phoenix_evidence._ppi import corrected_rate
print('TAIL',[(n,log_evidence(0,n,.05),math.log(19/(n+19))) for n in [1000,10000,15000,100000]])
print('PARTIAL_NULL',canary([('first 5 high-rate examples',5,5)],.05))
print('MISSING',count_flips({'a':1,'b':1},{'a':[1]}))
try: print('JURY',jury([['a','b'],['b','a']],['a','a']))
except Exception as e: print('JURY',type(e).__name__,str(e))
print('PAIR',pair_accuracy([('a','b')],{'a':'yes','b':'no'},{'a':['yes','wrong'],'b':['no']}))
print('DOCTOR',diagnose([Example('a',{'x':'1.0'},'a'),Example('b',{'x':'1,0'},'b')]))
for p in [.01,.02,.05,.1,.2,.5]:
 widths=[None]+[_human_width(n,p,.05) for n in range(1,151)]
 found=False
 for n in range(2,150):
  if widths[n+1]>widths[n]:
   target=(widths[n]+widths[n+1])/2
   got=_smallest(lambda k: widths[k],target,150)
   expected=next(k for k in range(1,151) if widths[k]<=target)
   if got!=expected:
    print('PRICE',dict(p=p,target=target,got=got,expected=expected,w_before=widths[n],w_after=widths[n+1])); found=True;break
 if found:break
# exact all nonempty Bernoulli draws, empty draw separately
f=[.9]*10; y=[0.]*10; pi=[.5]*10
out=[]
for bits in itertools.product([0,1],repeat=10):
 h={i:y[i] for i,b in enumerate(bits) if b}
 if h: out.append(corrected_rate(f,h,pi).estimate)
print('CLIPPED_BIAS',sum(out)/len(out),'truth',0,'empty_probability',1/1024)
