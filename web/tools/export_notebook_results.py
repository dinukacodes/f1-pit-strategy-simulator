import sys, json, math
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from f1sim import *
import numpy as np
SEED=20251005
p=default_params()
out={}
SEED_STAGE1, SEED_STAGE2 = SEED + 11, SEED + 22
cands = candidate_strategies(p)
cands += [strategy([L], c, reactive_window=(12, L)) for c in (("MEDIUM", "HARD"), ("HARD", "MEDIUM")) for L in range(20, 46, 2)]
ranked = screen(cands, p, 1000, SEED_STAGE1)
out['n_candidates']=len(cands)
out['stage1_top']=[dict(name=s['name'],mean_s=float(m)) for m,s in ranked[:8]]
def best_of(pred): return next(s for m, s in ranked if pred(s))
best1 = best_of(lambda s: len(s["pit_laps"]) == 1 and s["reactive_window"] is None)
best2 = best_of(lambda s: len(s["pit_laps"]) == 2)
bestR = best_of(lambda s: s["reactive_window"] is not None)
SL=[best1,best2,bestR]
out['shortlist']=[dict(name=s['name'],pit_laps=s['pit_laps'],compounds=s['compounds'],reactive_window=s['reactive_window']) for s in SL]
z_b = bonferroni_z(2)
rows, X2 = paired_table(SL, p, 10_000, SEED_STAGE2, ref=0, z=z_b)
out['stage2']=[{k:(float(v) if not isinstance(v,str) else v) for k,v in r.items()} for r in rows]
out['bonferroni_z']=z_b
out['crn_ratio']=float(variance_reduction_ratio(best1, best2, p, 10_000, SEED + 33))
P_GS_SWEEP = [0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.06]
sw=[]
for v in P_GS_SWEEP:
    q = with_params(p, p_gs=v)
    X = run_paired(SL, q, 10_000, SEED + 100 + int(v * 1e4))
    sw.append(dict(p_gs=v, two=list(map(float,mean_ci(X[:,1]-X[:,0]))), react=list(map(float,mean_ci(X[:,2]-X[:,0])))))
out['sweep']=sw
SENS = {"p_gs":[0.0,0.02,0.04,0.06],"alpha_sc":[0.25,0.43,0.60],"sc_min_laps":[2,3,4],"crew_sigma":[0.3,0.5,0.8],"k_hard":[0.025,0.035,0.050]}
sr=[]
for name, values in SENS.items():
    for v in values:
        if name == "alpha_sc": q = with_params(p, alpha_sc=v, alpha_vsc=p["alpha_vsc"])
        elif name == "k_hard":
            ks = dict(p["k_s_per_lap"]); ks["HARD"] = v; q = with_params(p, k_s_per_lap=ks)
        else: q = with_params(p, **{name: v})
        X = run_paired(SL[:2], q, 4000, SEED + 500)
        m, lo, hi = mean_ci(X[:, 1] - X[:, 0])
        sr.append(dict(param=name, value=v, mean=float(m), lo=float(lo), hi=float(hi)))
out['sensitivity']=sr
out['status_probs']=status_probabilities(p).tolist()
out['renewal']=renewal_fractions(p).tolist()
out['alphas']=[p['alpha_vsc'],p['alpha_sc']]
# exact check values (5.4)
cs=[strategy([26], ["MEDIUM", "HARD"]), strategy([18, 40], ["SOFT", "MEDIUM", "HARD"])]
out['exact']=[dict(p_gs=v, name=s['name'], exact=exact_expected_total(s, linear_params(with_params(p,p_gs=v)))) for v in (0.0,0.02,0.05) for s in cs]
pd_ = linear_params(p); pd_.update(random=False, p_gv=0.0, p_gs=0.0, p_lap1_sc=0.0)
out['L_star']=optimal_one_stop_lap("MEDIUM","HARD",pd_)
out['det_bench']={L: simulate_race(strategy([L], ["MEDIUM", "HARD"]), pd_, 0)["total_time"] for L in range(8,55)}
json.dump(out, open(os.path.join(os.path.dirname(__file__), '..', 'site', 'data', 'notebook_results.json'),'w'), indent=1)
# CRN scenario fixture for exact JS test
scen=draw_scenarios(300,p,SEED)
tests=[strategy([34],["HARD","MEDIUM"]),strategy([19,46],["MEDIUM","HARD","SOFT"]),strategy([28],["MEDIUM","HARD"],reactive_window=(12,28))]
fx=dict(status=scen['status'].tolist(), z_lap=scen['z_lap'].tolist(), z_crew=scen['z_crew'].tolist(),
  strategies=[dict(pit_laps=s['pit_laps'],compounds=s['compounds'],reactive_window=s['reactive_window']) for s in tests],
  totals=[simulate_scenarios(s,p,scen).tolist() for s in tests])
json.dump(fx, open(os.path.join(os.path.dirname(__file__), 'python_fixture.json'),'w'))
print(json.dumps({k:out[k] for k in ['stage2','crn_ratio','shortlist']},indent=1))
for r in sw: print(r)
