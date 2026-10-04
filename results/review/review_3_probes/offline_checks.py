import sys, json, runpy, importlib, random, math, subprocess, os
from pathlib import Path
from types import SimpleNamespace
R=Path('<repo>'); S=Path('<review-scratch>')
sys.path[:0]=[str(R),str(R/'bench')]
from phoenix_evidence.phoenix import judge_canary
from phoenix_evidence._price import price_of_certainty,_human_width
from phoenix_evidence._canary import canary
# Real adapter, fake transport. Equal numerical score, changed categorical label.
def experiment(label,score,indices=range(100)):
 return {'name':label,'task_runs':[{'id':str(i),'dataset_example_id':str(i),'repetition_number':1} for i in indices], 'evaluation_runs':[{'experiment_run_id':str(i),'name':'judge','result':{'label':label,'score':score}} for i in indices]}
exps={'ref':experiment('A',1),'changed':experiment('B',1),'partial':experiment('B',0,range(5)), 'missing':experiment('A',1,range(1))}
c=SimpleNamespace(experiments=SimpleNamespace(get_experiment=lambda experiment_id:exps[experiment_id]))
for name in ['changed','partial','missing']:
 r=judge_canary(c,'ref',[name],'judge',.05); print('ADAPTER',name,r.looks[-1])
# A single legitimate 1/10 noisy observation, repeated ID manufactures evidence
exps['tenref']=experiment('A',1,range(10));exps['oneflip']=experiment('A',1,range(10));exps['oneflip']['evaluation_runs'][0]['result']['score']=0
r=judge_canary(c,'tenref',['oneflip']*100,'judge',.05);print('REPLAY',r.first_alarm)
p=price_of_certainty(150,.0875501642259883,.002,1,pass_rate=.01);print('PRICE',p.human_only,'width41',_human_width(41,.01,.05),'width62',_human_width(62,.01,.05))
# offline benches: redirect every benchmark output; no CachedJudge constructor mkdir or calls
import certify_phoenix_suites as cert

def readonly_init(self,suite,evaluator,model='unused'):
 self.cache={r['key']:r for r in map(json.loads,(R/'results/judgments'/f'{suite}.jsonl').read_text().splitlines())}
cert.CachedJudge.__init__=readonly_init
for name in ['dataset_doctor','pair_consistency','effective_judges']:
 m=importlib.import_module(name);m.OUT=S if name!='dataset_doctor' else S/'dataset_doctor.json'
 m.main()
 fn={'dataset_doctor':'dataset_doctor.json','pair_consistency':'pair_consistency.json','effective_judges':'effective_judges.json'}[name]
 print('MATCH',name,json.loads((S/fn).read_text())==json.loads((R/'results'/fn).read_text()))
rows=list(map(json.loads,(R/'results/judgments/e2e_low.jsonl').read_text().splitlines()));print('E2E',len(rows),sorted(set(r['model'] for r in rows)))
# same Monte Carlo loop, suppress expensive unrelated naive baseline; no output writes
import canary_sim
canary_sim.naive_alarm_day=lambda daily:None
for seed,same in [(0,False),(10,True)]:
 print('CANARY_SIM',canary_sim.run(0,seed,same_rates=same)['canary'],flush=True)
