import sys,os,json,subprocess,ast,importlib
from pathlib import Path
R=Path('<repo>');S=Path('<review-scratch>');sys.path[:0]=[str(R),str(R/'bench')]
# Run the exact compare shell body, with only executable replaced by argv recorder.
action=(R/'action.yml').read_text().split('      run: |\n',1)[1]
script='\n'.join(line[8:] for line in action.splitlines())
bin=S/'bin';bin.mkdir(exist_ok=True)
stub=bin/'phoenix-evidence';stub.write_text('#!/bin/bash\nprintf \'<%s>\\n\' "$@"\n');stub.chmod(0o755)
attack='$(touch <review-scratch>/INJECTED); "quoted"\nsecond line'
env=os.environ|{'PATH':str(bin)+':'+os.environ['PATH'],'RUNNER_TEMP':str(S),'GITHUB_OUTPUT':str(S/'github_output'),'PE_BASE':attack,'PE_CANDIDATE':attack,'PE_LOWER':attack,'PE_URL':attack,'PE_FAIL':'true'}
r=subprocess.run(['bash','-e','-o','pipefail','-c',script],env=env,text=True,capture_output=True)
print('ACTION',r.returncode,'injected',(S/'INJECTED').exists(),'literal payload occurrences',r.stdout.count(attack))
from phoenix_evidence.phoenix import _experiment_name
from types import SimpleNamespace
c=SimpleNamespace(experiments=SimpleNamespace(get=lambda **kw:{'name':'baseline'}));print('NAME',_experiment_name(c,'123'))
from phoenix_evidence._price import price_of_certainty
p=price_of_certainty(10000,.1,.002,.5,disagreement=.05);print('PRICE_HEADLINE',p.human_only.labels,p.corrected.labels,p.break_even_human_cost)
# Frozen cached real-canary checks re-evaluated, no judge calls.
from phoenix_evidence._canary import canary
raw=json.loads((R/'results/canary_real.json').read_text());r=canary([(x['label'],x['checks'],x['flips']) for x in raw['looks']],raw['allowed'])
print('REAL_CANARY_RECOMPUTE',r.looks[-1].evidence,r.drifted)
# Check default floor actual ratio.
from phoenix_evidence._ppi import plan_labels
_,pi=plan_labels([0,1]*100,40);print('FLOOR',min(pi),max(pi),max(pi)/min(pi))
# Rerun probability simulation on 200 draws at one stated scenario.
import planner_probabilities as pp
pp.REPS=200
for x in pp.run('calibrated',100,3):
 if x['design'] in ['uniform / hard label','sqrt(p(1-p)) / probability']:print('PPI_PROB',x,flush=True)
