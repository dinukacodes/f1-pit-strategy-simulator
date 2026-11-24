"""Build notebook/f1_pit_strategy_simulator.ipynb from src/f1sim.py plus the cells below.

src/f1sim.py is the single source of truth for the model code; this script
splits it into one notebook cell per section so the notebook is
self-contained in Colab. Run:  python tools/build_notebook.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "src", "f1sim.py"), encoding="utf-8").read()
CAL = open(os.path.join(ROOT, "src", "calibrate.py"), encoding="utf-8").read()

cells = []


def md(text):
    cells.append(dict(cell_type="markdown", id="c%02d" % len(cells), metadata={}, source=text.strip("\n")))


def code(text):
    cells.append(dict(cell_type="code", id="c%02d" % len(cells), metadata={}, execution_count=None, outputs=[], source=text.strip("\n")))


def module_sections(src):
    """Split f1sim.py into (title, code) blocks at its '# ----' section banners."""
    parts = re.split(r"\n# -{20,}\n# (.+)\n# -{20,}\n", src)
    head = parts[0]
    out = [("Header and imports", head)]
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), parts[i + 1]))
    return out


# ---------------------------------------------------------------------------
md(r"""
# F1 Pit-Stop Strategy Simulator: Safety-Car Uncertainty at Singapore

**Summary.** This notebook simulates a 62-lap Formula 1 race at Singapore to compare one-stop, two-stop and *pit-if-neutralised* tyre strategies when Safety Car (SC) and Virtual Safety Car (VSC) periods occur at random. Tyre wear follows a fuel-coupled, self-accelerating ODE solved with **RK4**. Track status follows a lap-wise **Markov chain** with a phase-type minimum Safety-Car length. Pit losses are derived from pit-lane geometry. Stationary crew times and lap noise are generated with **inverse-transform and Box–Muller** samplers. Strategies are compared with **two-stage Monte Carlo using common random numbers (CRN)**, reporting 95% confidence intervals for paired race-time differences. The simulator is verified against closed-form ODE solutions, a deterministic benchmark with a derived optimum, the Markov chain's stationary distribution, and an **exact expected-race-time formula** that the Monte Carlo must reproduce.

*Run with Runtime → Run all. No data downloads are needed. Seeds are fixed and printed. Parameters marked "assumed" are documented in §3 and tested in the sensitivity study.*
""")

code(r"""
# Install / check dependencies (pre-installed on Colab; pins match requirements.txt)
!pip install -q "numpy>=1.24" "matplotlib>=3.7"
""")

code(r"""
import os, math, time
import numpy as np
import matplotlib.pyplot as plt

SEED = 20251005                      # master seed for every experiment (printed below)
FIG_DIR = "../figures" if os.path.isdir("../figures") else "figures"   # repo layout or Colab
os.makedirs(FIG_DIR, exist_ok=True)
print("numpy", np.__version__, "| master seed", SEED, "| figures ->", FIG_DIR)
""")

# ---------------------------------------------------------------------------
md(r"""
## 2. Problem and question

Formula 1 teams trade the pace of fresh tyres against the time lost in the pit lane. A stop taken under SC or VSC is cheaper, because cars on track slow down while the pit lane keeps its speed limit. Singapore is the extreme case: every race from 2008 to 2023 had at least one Safety Car, but 2024 and 2025 had none. The 2025 pit-lane speed limit rise (60 → 80 km/h) also cut the pit loss by roughly 6 s.

**Question.** For a 62-lap Singapore race, how does the expected race-time difference (with 95% CI) between the best one-stop, two-stop and pit-if-neutralised strategies change as the per-lap SC onset probability $P_{GS}$ varies, and at what $P_{GS}$ does the preferred strategy switch?

**Scope.** One car, no traffic or positions (objective: expected race time); dry race; no red flags; no refuelling.
""")

# ---------------------------------------------------------------------------
md(r"""
## 3. Model, assumptions and equations

### 3.1 Assumptions
| # | Assumption | Why | Unlocks |
|---|---|---|---|
| H1 | Lap-discrete time, fixed 62 laps, no red flags | Status, stops and tyre life are logged per lap | finite-horizon DTMC |
| H2 | Track status is exogenous (independent of our strategy) | one car barely affects incident risk | valid CRN pairing |
| H3 | Markov and time-homogeneous after lap 1; separate lap-1 onset | lap-1 incidents are over-represented | exact marginals via $P^\ell$ |
| H4 | SC lasts at least $m$ laps (phase-type), then geometric | real SCs last ≈2–8 laps | closed-form duration law |
| H5 | VSC/SC end in Green | escalations are rare | renewal-reward stationary law |
| H6 | Under VSC/SC lap time $=k_s t_0$, set by the neutralisation | cars follow the SC / VSC delta | SC laps cancel in paired differences |
| H7 | Green lap time is additive and separable | standard in race simulation | linearity of expectation |
| H8 | Smooth, self-accelerating tyre wear ODE | worn tyres overheat; no cliff inside a stint | closed form, convex stint cost, meaningful RK4 order |
| H9 | Pit lane at constant limit speed; bypassed section slows by $k_s$ | pit limiter | derived $\alpha_s$ |
| H10 | i.i.d. Gaussian lap noise, i.i.d. shifted-lognormal crew time | standard input models | CLT, exact sampler tests |
| H11 | Risk-neutral objective (expected race time) | single car, no positions | well-posed comparison |
| H12 | Race time is non-decreasing in every common random input | true by construction | CRN cannot increase variance |
| H13 | Stage 2 uses fresh seeds, shortlist fixed beforehand | avoids winner's-curse bias | unbiased final estimates |

### 3.2 Tyre wear and fuel (numerical ODE solvers)
Fuel mass on race lap $\ell$: $m(\ell)=m_0-b(\ell-1)$ [kg]. Tyre degradation $w$ [s] with tyre age $a$ [laps] in a stint starting on lap $s$:
$$\frac{dw}{da}=k_c\,(1+\beta\,m(s+a))\,(1+\eta\,w)\,\varphi(\text{status}),\qquad w(0)=0,$$
with $\varphi=1,\ \varphi_V,\ \varphi_S$ for Green, VSC, SC. For constant $\varphi$ the equation separates, giving the exact solution used for verification:
$$w(a)=\frac{e^{\eta k_c\varphi A(a)}-1}{\eta},\qquad A(a)=\big(1+\beta(m_0-b(s-1))\big)a-\tfrac{\beta b}{2}a^2 .$$
The simulator integrates one lap per RK4 step (status, and hence $\varphi$, is constant within a lap):
$$y_{n+1}=y_n+\tfrac{h}{6}(k_1+2k_2+2k_3+k_4),\qquad \text{global error }O(h^4).$$
Since the growth rate $\lambda=\eta k_c(1+\beta m)\approx 10^{-3}$ per lap, $|h\lambda|\ll 1$ and the scheme is stable at $h=1$ lap. *If $\eta=0$ the right-hand side depends only on $a$, and RK4 reduces to Simpson's rule and is exact. That is why $\eta>0$ is kept, so the order study is meaningful.*

### 3.3 Lap time
$$t_\ell=\begin{cases}t_0+\Delta_c+w_\ell+\gamma\,m(\ell)+\sigma\varepsilon_\ell, & \text{Green},\ \varepsilon_\ell\sim N(0,1)\\ k_s\,t_0, & \text{VSC/SC}\end{cases}$$
The fuel term $\gamma m(\ell)$ depends only on the lap, so it **cancels** in strategy differences. Fuel influences strategy only through the wear coupling $\beta$.

### 3.4 Track status (Markov chain)
States $\{G, V, SC_1,\dots,SC_m, SC^+\}$, where $SC_i\to SC_{i+1}$ with probability 1 and $SC_m, SC^+$ continue with $p_{SS}$. The SC duration is therefore $D=m+\text{Geom}$ with
$$E[D_S]=m+\frac{p_{SS}}{1-p_{SS}},\qquad \hat p_{SS}=\frac{\sum_i(D_i-m)}{\sum_i(D_i-m+1)}.$$
Long-run fractions by renewal-reward (H5), with onset probabilities $a=P_{GV}$ and $c=P_{GS}$:
$$\pi_G=\frac{1}{1+aE[D_V]+cE[D_S]},\quad \pi_V=aE[D_V]\pi_G,\quad \pi_S=cE[D_S]\pi_G .$$
The exact lap marginals are $p(\ell)=p(1)P^{\ell-1}$. Transition probabilities are estimated by maximum likelihood $\hat P_{ij}=n_{ij}/\sum_k n_{ik}$, with Beta credible intervals.

### 3.5 Pit loss (derived from geometry)
Green net transit loss: $\Delta T_G=T_{pit}-T_{bypass}$. Under neutralisation $s$ the bypassed section takes $k_sT_{bypass}$, but the speed-limited lane does not change:
$$\Delta T_s=(1-\alpha_s)\Delta T_G,\qquad \alpha_s=\frac{(k_s-1)\,T_{bypass}}{\Delta T_G}.$$
Total in-lap loss $=(1-\alpha_s)\Delta T_G + C$, with stationary time $C=c_0+e^{\mu+\sigma Z}$ (shifted lognormal, never scaled).

### 3.6 Analytic results used as verification references
* **One-stop optimum** (linear wear, $\eta=\beta=0$): $f(L)$ is convex, with $f''=k_1+k_2$, and
  $L^*=\dfrac{k_2N+(\Delta_2-\Delta_1)+(k_1-k_2)/2}{k_1+k_2}$.
* **One vs two stops, Green, equal stints:** a two-stop wins iff $kN^2/12>\Delta T_G+E[C]$.
* **Exact expectation for fixed strategies** (H2–H7, $\eta=\beta=0$, $\varphi=1$):
  $E[T]=\sum_\ell \big(p_G(\ell)\,g_\ell+p_V(\ell)k_Vt_0+p_S(\ell)k_St_0\big)+\sum_{L\in\mathcal L}\big(E[C]+\Delta T_G(1-\alpha_V p_V(L)-\alpha_S p_S(L))\big)$.

### 3.7 Monte Carlo with common random numbers
$\operatorname{Var}(T_B-T_A)=\operatorname{Var}T_A+\operatorname{Var}T_B-2\operatorname{Cov}(T_A,T_B)$. Race times are non-decreasing in the shared inputs (H12), so $\operatorname{Cov}\ge 0$ and CRN cannot increase the variance. Each source has its own random stream, so strategies with different numbers of stops still use the same scenario. CI: $\bar D\pm z\,s_D/\sqrt n$, with a Bonferroni-adjusted $z$ for multiple comparisons. The required sample size is $n\ge(z s_D/h^*)^2$.

### 3.8 Concepts applied
| Equation / algorithm | Concept |
|---|---|
| Tyre-wear ODE, RK4 (and Euler/RK2 for comparison), error order $O(h^4)$ | Numerical ODE solvers |
| Box–Muller normals; shifted-lognormal and DTMC sampling by inverse transform; KS tests | Input modelling and random variate generation |
| Phase-type track-status chain, $p(\ell)=p(1)P^{\ell-1}$, $\pi=\pi P$, MLE of $P$ | Discrete-time Markov chains |
| CRN paired differences, CIs, $O(N^{-1/2})$ convergence, sample-size formula | Monte Carlo integration and the law of large numbers |
| Two-car pit-box queue with an event list (next-event time advance) | Discrete-event simulation |
| Transition counts → $\hat P$, Beta posteriors, phase-type duration fit, held-out tests | Input modelling from real data |
""")

code(r"""
# Parameter table with units and provenance (see PARAM_SOURCES in the implementation)
""")  # placeholder replaced after implementation cells (needs functions defined)
cells.pop()

# ---------------------------------------------------------------------------
md(r"""
## 4. Implementation

The model code is below, one cell per component (source of truth: `src/f1sim.py` in the repository). Units: seconds [s], kilograms [kg], laps. Status codes: 0 Green, 1 VSC, 2 SC.
""")
for title, body in module_sections(SRC):
    md("### 4.%d %s" % (len([c for c in cells if c["cell_type"] == "markdown" and c["source"].startswith("### 4.")]) + 1, title))
    code(body.strip("\n"))

code(r"""
p = default_params()
print("Derived pit-loss reductions: alpha_VSC = %.3f, alpha_SC = %.3f (Green net transit loss %.1f s)"
      % (p["alpha_vsc"], p["alpha_sc"], p["dT_green_s"]))
for k in ("n_laps", "t0_s", "sigma_s", "k_vsc", "k_sc", "phi_vsc", "phi_sc", "p_gv", "p_gs", "p_lap1_sc",
          "p_vv", "sc_min_laps", "p_ss", "t_pit_s", "t_bypass_s", "crew_shift_s", "crew_mu", "crew_sigma"):
    print("  %-14s = %s" % (k, p[k]))
print("  wear rate k_c [s/lap]:", p["k_s_per_lap"], "| pace offset [s]:", p["offset_s"])
print("\nProvenance:")
for k, v in PARAM_SOURCES.items():
    print("  %-48s %s" % (k, v))
""")

# ---------------------------------------------------------------------------
md(r"""
## 5. Verification

Every check below ends in an `assert`, so a failure stops **Run all**. Each one states what is tested, the expected result and the tolerance.
""")

md(r"""
### 5.1 RK4 against the model's own closed-form solution, and error order
The expected result is that RK4 matches $w(a)$ from §3.2 to better than $10^{-8}$ s over a 30-lap stint at $h=1$ lap. The fitted log–log slopes should be ≈1 (Euler), 2 (RK2) and 4 (RK4) within ±0.3. The tolerances come from truncation error, with round-off far smaller.
""")
code(r"""
pv = with_params(p, eta_per_s=0.08)          # stronger nonlinearity makes the order study visible
f = wear_rhs(pv, "SOFT", 1, 1.0)
exact = float(wear_closed_form(pv, "SOFT", 1, 30.0))
w_rk4 = float(rk4_solve(f, 0.0, 0.0, 30.0, 30))
print("w(30) exact = %.10f s, RK4 (h=1) = %.10f s, error %.2e s" % (exact, w_rk4, abs(w_rk4 - exact)))
assert abs(w_rk4 - exact) < 1e-8

hs = np.array([6.0, 3.0, 2.0, 1.5, 1.0])
orders = {}
plt.figure(figsize=(5.5, 4))
for name, solver in (("Euler", euler_solve), ("RK2", rk2_solve), ("RK4", rk4_solve)):
    errs = np.array([abs(float(solver(f, 0.0, 0.0, 30.0, int(round(30 / h)))) - exact) for h in hs])
    orders[name] = np.polyfit(np.log(hs), np.log(errs), 1)[0]
    plt.loglog(hs, errs, "o-", label="%s (slope %.2f)" % (name, orders[name]))
plt.xlabel("step size h [laps]"); plt.ylabel("|w(30) error| [s]"); plt.title("ODE solver convergence")
plt.legend(); plt.grid(True, which="both", alpha=.3); plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "convergence_ode.png"), dpi=150); plt.show()
print("measured orders:", {k: round(v, 2) for k, v in orders.items()})
assert abs(orders["Euler"] - 1) < 0.3 and abs(orders["RK2"] - 2) < 0.3 and abs(orders["RK4"] - 4) < 0.3
print("PASS 5.1")
""")

md(r"""
### 5.2 Deterministic benchmark with a derived optimum
With all randomness off, linear wear and $P_{GV}=P_{GS}=0$, the simulated race time of every one-stop MEDIUM→HARD strategy must equal the closed form (stint cost $S\Delta_c+k_cS(S-1)/2$ plus pit loss) to $10^{-6}$ s. The best integer pit lap must be $\lfloor L^*\rfloor$ or $\lceil L^*\rceil$ from §3.6, and the one- vs two-stop rule must agree with the simulator.
""")
code(r"""
pd_ = linear_params(p); pd_.update(random=False, p_gv=0.0, p_gs=0.0, p_lap1_sc=0.0)
crew_det = pd_["crew_shift_s"] + math.exp(pd_["crew_mu"])
laps = range(8, 55)
sim = {L: simulate_race(strategy([L], ["MEDIUM", "HARD"]), pd_, 0)["total_time"] for L in laps}
ana = {L: green_total_linear(strategy([L], ["MEDIUM", "HARD"]), pd_) + pd_["dT_green_s"] + crew_det for L in laps}
worst = max(abs(sim[L] - ana[L]) for L in laps)
L_star = optimal_one_stop_lap("MEDIUM", "HARD", pd_)
best = min(sim, key=sim.get)
print("max |sim - analytic| = %.2e s; L* = %.2f; simulated best lap = %d" % (worst, L_star, best))
assert worst < 1e-6
assert best in (math.floor(L_star), math.ceil(L_star))
k_be = two_stop_break_even_k(pd_)
print("Green break-even wear rate for one vs two equal MEDIUM stints: k* = %.4f s/lap (MEDIUM k = %.3f)" % (k_be, pd_["k_s_per_lap"]["MEDIUM"]))
one = simulate_race(strategy([31], ["MEDIUM", "HARD"]), with_params(pd_, k_s_per_lap={"SOFT": .1, "MEDIUM": .06, "HARD": .06}, offset_s={"SOFT": 0, "MEDIUM": 0, "HARD": 0}), 0)["total_time"]
two = simulate_race(strategy([21, 42], ["MEDIUM", "HARD", "MEDIUM"]), with_params(pd_, k_s_per_lap={"SOFT": .1, "MEDIUM": .06, "HARD": .06}, offset_s={"SOFT": 0, "MEDIUM": 0, "HARD": 0}), 0)["total_time"]
assert (two < one) == (0.06 > k_be)
print("PASS 5.2")
""")

md(r"""
### 5.3 Markov chain: validity, stationarity and Safety-Car duration law
Every matrix in the $P_{GS}$ sweep must have non-negative entries and rows summing to 1. A $10^5$-lap run of the expanded chain must reproduce the renewal-reward fractions (§3.4) within 0.01. The simulated SC lengths must never be shorter than $m$, and their mean must match $E[D_S]$ within 3 standard errors.
""")
code(r"""
P_GS_SWEEP = [0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.06]
for v in P_GS_SWEEP:
    q = with_params(p, p_gs=v)
    for M in (lumped_matrix(q), expanded_matrix(q)[0]):
        assert M.min() >= 0 and np.allclose(M.sum(1), 1.0)
P, collapse = expanded_matrix(p)
path = collapse[simulate_track_status(P, 100_000, np.random.default_rng(SEED), 0)]
emp = np.bincount(path, minlength=3) / len(path)
pi_renewal = renewal_fractions(p)
pi_eig = np.array([stationary_distribution(P)[collapse == k].sum() for k in range(3)])
print("empirical", emp.round(4), "| renewal formula", pi_renewal.round(4), "| eigen-solve", pi_eig.round(4))
assert np.allclose(pi_renewal, pi_eig, atol=1e-10) and np.max(np.abs(emp - pi_renewal)) < 0.01
runs, n = [], 0
for s in path:
    if s == SC: n += 1
    elif n: runs.append(n); n = 0
runs = np.array(runs)
se = runs.std(ddof=1) / math.sqrt(len(runs))
print("SC periods: %d, min length %d laps (m = %d), mean %.3f laps vs E[D] = %.3f" % (len(runs), runs.min(), p["sc_min_laps"], runs.mean(), sc_mean_duration(p)))
assert runs.min() >= p["sc_min_laps"] and abs(runs.mean() - sc_mean_duration(p)) < 3 * se
m_hat, pss_hat = mle_sc_persistence(runs)
print("MLE recovers m = %d, p_SS = %.3f (true %.2f)" % (m_hat, pss_hat, p["p_ss"]))
assert m_hat == p["sc_min_laps"] and abs(pss_hat - p["p_ss"]) < 0.03
print("PASS 5.3")
""")

md(r"""
### 5.4 Exact expected race time vs Monte Carlo (independent check of the whole stochastic pipeline)
In the analytically tractable case ($\eta=\beta=0$, $\varphi=1$), the exact expectation from §3.6 uses only matrix powers of the chain. The Monte Carlo mean from 40,000 races must lie within 3 standard errors of it, for every strategy and for three values of $P_{GS}$.
""")
code(r"""
check_strats = [strategy([26], ["MEDIUM", "HARD"]), strategy([18, 40], ["SOFT", "MEDIUM", "HARD"])]
for v in (0.0, 0.02, 0.05):
    q = linear_params(with_params(p, p_gs=v))
    X = run_paired(check_strats, q, 40_000, SEED + 1)
    for j, s in enumerate(check_strats):
        ex = exact_expected_total(s, q)
        se = X[:, j].std(ddof=1) / math.sqrt(len(X))
        print("P_GS=%.2f %-22s exact %.3f s | MC %.3f s | z = %+.2f" % (v, s["name"], ex, X[:, j].mean(), (X[:, j].mean() - ex) / se))
        assert abs(X[:, j].mean() - ex) < 3 * se
print("PASS 5.4")
""")

md(r"""
### 5.5 Conservation, limiting cases and model rules
These checks confirm that:
* every race has 62 laps and its total equals the sum of its laps;
* fuel never goes negative;
* tyre age resets at each stop;
* the stationary time is added unscaled, and only net transit is reduced by $(1-\alpha_s)$;
* $\alpha=0$ makes neutralised stops cost the same as Green stops;
* identical strategies under CRN differ by exactly 0;
* single-compound and out-of-range strategies are rejected;
* the loop and vectorised implementations agree to $10^{-9}$ s.
""")
code(r"""
s1 = strategy([26], ["MEDIUM", "HARD"])
r = simulate_race(s1, p, SEED)
assert len(r["lap_times"]) == p["n_laps"] and abs(r["total_time"] - r["lap_times"].sum()) < 1e-9
assert r["fuel_kg"].min() >= 0 and np.all(np.diff(r["fuel_kg"]) <= 0)
assert r["tyre_age"][r["pit_laps"][0]] == 0
for st, a in ((VSC, p["alpha_vsc"]), (SC, p["alpha_sc"])):
    assert abs((pit_loss(st, 2.5, p) - 2.5) - (1 - a) * (pit_loss(GREEN, 2.5, p) - 2.5)) < 1e-12
q0 = with_params(p, alpha_vsc=0.0, alpha_sc=0.0)
assert pit_loss(SC, 2.5, q0) == pit_loss(GREEN, 2.5, q0)
X = run_paired([s1, s1], p, 500, SEED)
assert np.max(np.abs(X[:, 0] - X[:, 1])) == 0
assert not validate_strategy(strategy([26], ["HARD", "HARD"]), p)
assert not validate_strategy(strategy([70], ["SOFT", "HARD"]), p)
scen = draw_scenarios(200, p, SEED)
s3 = strategy([30], ["MEDIUM", "HARD"], reactive_window=(14, 30))
assert np.max(np.abs(simulate_scenarios(s3, p, scen) - [simulate_race_loop(s3, p, scen, i) for i in range(200)])) < 1e-9
print("PASS 5.5")
""")

md(r"""
### 5.6 Random variate generators (Kolmogorov–Smirnov)
Box–Muller output must be N(0,1), and crew times must follow the shifted lognormal. Each KS statistic must be below the 5% critical value $1.36/\sqrt n$, and no crew time may fall below the shift.
""")
code(r"""
def ks_stat(x, cdf):
    # One-sample Kolmogorov-Smirnov statistic D_n
    x = np.sort(np.asarray(x)); n = len(x); F = cdf(x)
    return max(np.max(np.arange(1, n + 1) / n - F), np.max(F - np.arange(n) / n))

norm_cdf = np.vectorize(lambda v: 0.5 * (1 + math.erf(v / math.sqrt(2))))
rng = np.random.default_rng(SEED + 2)
z = box_muller(5000, rng)
c = sample_crew_time(5000, p, rng)
shift, mu, sg = crew_time_params(p)
D_z = ks_stat(z, norm_cdf)
D_c = ks_stat(c, lambda v: norm_cdf((np.log(v - shift) - mu) / sg))
crit = 1.36 / math.sqrt(5000)
print("Box-Muller: mean %.3f sd %.3f KS D %.4f | crew: min %.3f s, mean %.3f s (theory %.3f s), KS D %.4f | critical %.4f"
      % (z.mean(), z.std(), D_z, c.min(), c.mean(), shift + math.exp(mu + sg**2 / 2), D_c, crit))
assert D_z < crit and D_c < crit and c.min() > shift
print("PASS 5.6")
""")

md(r"""
### 5.7 Monte Carlo error falls as $N^{-1/2}$
The standard deviation of the mean race time across 30 independent batches is fitted on a log–log scale. The expected slope is −0.5 ± 0.15.
""")
code(r"""
Ns = np.array([100, 400, 1600, 6400])
sds = [np.std([run_paired([s1], p, n, SEED + 1000 * j + n)[:, 0].mean() for j in range(30)], ddof=1) for n in Ns]
slope = np.polyfit(np.log(Ns), np.log(sds), 1)[0]
plt.figure(figsize=(5.5, 4)); plt.loglog(Ns, sds, "o-", label="batch SD of mean (slope %.2f)" % slope)
plt.loglog(Ns, sds[0] * np.sqrt(Ns[0] / Ns), "k--", label=r"$N^{-1/2}$ reference")
plt.xlabel("replications N"); plt.ylabel("SD of mean race time [s]"); plt.title("Monte Carlo convergence")
plt.legend(); plt.grid(True, which="both", alpha=.3); plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "convergence_mc.png"), dpi=150); plt.show()
assert abs(slope + 0.5) < 0.15
print("PASS 5.7 (slope %.3f)" % slope)
""")


md(r"""
### 5.8 Second independent check: exact paired-difference curve vs Monte Carlo
§5.4 checked single expectations. Here the *decision quantity* itself, the expected paired difference $E[T_B-T_A]$ between a two-stop and a one-stop, is computed exactly from matrix powers of the chain (§3.6) for 13 values of $P_{GS}$, and the Monte Carlo paired CIs are overlaid. Every exact value must sit inside its 99.7% Monte Carlo interval. This check shares no code path with the simulator except the parameter dictionary.
""")
code(r"""
sA_, sB_ = strategy([26], ["MEDIUM", "HARD"]), strategy([18, 40], ["SOFT", "MEDIUM", "HARD"])
grid = np.linspace(0.0, 0.08, 13)
ex_d, mc_m, mc_h = [], [], []
for v in grid:
    q = linear_params(with_params(p, p_gs=v))
    ex_d.append(exact_expected_total(sB_, q) - exact_expected_total(sA_, q))
    X = run_paired([sA_, sB_], q, 20_000, SEED + 4000 + int(v * 1e4))
    d = X[:, 1] - X[:, 0]
    mc_m.append(d.mean()); mc_h.append(3 * d.std(ddof=1) / math.sqrt(len(d)))
ex_d, mc_m, mc_h = map(np.array, (ex_d, mc_m, mc_h))
fig, ax = plt.subplots(figsize=(6.5, 4))
ax.plot(grid, ex_d, "k-", lw=2, label="exact (matrix powers)")
ax.errorbar(grid, mc_m, yerr=mc_h, fmt="o", color="C3", capsize=3, label="Monte Carlo mean ± 3 SE (20,000 paired races)")
ax.set_xlabel("$P_{GS}$"); ax.set_ylabel("E[two-stop − one-stop] [s]"); ax.set_title("Exact vs simulated paired difference")
ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "verification_exact_vs_mc.png"), dpi=150); plt.show()
zs = (mc_m - ex_d) / (mc_h / 3)
print("z-scores:", np.round(zs, 2))
assert np.all(np.abs(mc_m - ex_d) < mc_h)
print("PASS 5.8 (max |z| = %.2f over %d points)" % (np.abs(zs).max(), len(grid)))
""")

md(r"""
### 5.9 Two-car discrete-event model: reduction and queueing checks
The team model (§4, *Two-car team model*) must (a) reproduce the single-car simulator **exactly** for both cars when interaction is switched off, over 300 random races; (b) leave the lead car untouched when the stops never overlap; (c) make the second car wait exactly $C+\tau-g_0$ when both cars stop on the same lap in a deterministic race (crew time $C$, turnaround $\tau$, grid gap $g_0$); and (d) never let a car wait when the stops are on different laps.
""")
code(r"""
sT = strategy([26], ["MEDIUM", "HARD"])
a_sc, b_sc = draw_team_scenarios(300, p, SEED + 9)
q_off = team_params(p, interact=False)
TA = np.array([simulate_team_race(sT, sT, q_off, a_sc, b_sc, i)["total_a"] for i in range(300)])
TB = np.array([simulate_team_race(sT, sT, q_off, a_sc, b_sc, i)["total_b"] for i in range(300)])
err_a = np.max(np.abs(TA - simulate_scenarios(sT, p, a_sc))); err_b = np.max(np.abs(TB - simulate_scenarios(sT, p, b_sc)))
print("(a) no interaction: max |team - single| car A %.1e s, car B %.1e s" % (err_a, err_b))
assert err_a < 1e-9 and err_b < 1e-9
pdet = linear_params(p); pdet.update(random=False, p_gv=0.0, p_gs=0.0, p_lap1_sc=0.0)
r = simulate_two_car_race(strategy([18], ["MEDIUM", "HARD"]), strategy([36], ["MEDIUM", "HARD"]), pdet, 0)
single = simulate_race(strategy([18], ["MEDIUM", "HARD"]), pdet, 0)["total_time"]
print("(b) non-overlapping stops: car A %.6f s vs single car %.6f s" % (r["total_a"], single))
assert abs(r["total_a"] - single) < 1e-6 and r["stack_delay_b"] == 0
r = simulate_two_car_race(sT, sT, pdet, 0)
tq = team_params(pdet)
expect = (tq["crew_shift_s"] + math.exp(tq["crew_mu"])) + tq["box_turn_s"] - tq["grid_gap_s"]
print("(c) same-lap stops: car B waited %.6f s, expected C + tau - g0 = %.6f s" % (r["stack_delay_b"], expect))
assert abs(r["stack_delay_b"] - expect) < 1e-9
R = run_team(strategy([20], ["MEDIUM", "HARD"]), strategy([32], ["MEDIUM", "HARD"]), p, 300, SEED + 10)
print("(d) different laps: max wait A %.2f s, B %.2f s over 300 random races" % (R["stack_delay_a"].max(), R["stack_delay_b"].max()))
assert R["stack_delay_a"].max() == 0 and R["stack_delay_b"].max() == 0
print("PASS 5.9")
""")

# ---------------------------------------------------------------------------
md(r"""
## 6. Experiments and results

### 6.1 Stage 1: screening (1,000 common scenarios)
All legal one-stop and two-stop windows on the grid are screened, together with *pit-if-neutralised* variants of the one-stops: plan to stop at lap $L$, but stop earlier at the first VSC/SC between lap 12 and $L$. Shortlist rule, fixed in advance: the best one-stop, the best two-stop and the best reactive strategy.
""")
code(r"""
SEED_STAGE1, SEED_STAGE2 = SEED + 11, SEED + 22          # independent stages (H13)
cands = candidate_strategies(p)
cands += [strategy([L], c, reactive_window=(12, L)) for c in (("MEDIUM", "HARD"), ("HARD", "MEDIUM")) for L in range(20, 46, 2)]
t0 = time.perf_counter()
ranked = screen(cands, p, 1000, SEED_STAGE1)
print("screened %d strategies in %.1f s" % (len(cands), time.perf_counter() - t0))
def best_of(pred):
    return next(s for m, s in ranked if pred(s))
best1 = best_of(lambda s: len(s["pit_laps"]) == 1 and s["reactive_window"] is None)
best2 = best_of(lambda s: len(s["pit_laps"]) == 2)
bestR = best_of(lambda s: s["reactive_window"] is not None)
for m, s in ranked[:8]:
    print("  %.1f s  %s" % (m, s["name"]))
SHORTLIST = [best1, best2, bestR]
print("Shortlist:", [s["name"] for s in SHORTLIST])
""")

md(r"""
### 6.2 Stage 2: 10,000 fresh scenarios, paired 95% CIs (Bonferroni-adjusted)
Differences are relative to the best one-stop. With 2 comparisons, Bonferroni uses $z_{1-0.05/4}$.
""")
code(r"""
z_b = bonferroni_z(2)
rows, X2 = paired_table(SHORTLIST, p, 10_000, SEED_STAGE2, ref=0, z=z_b)
print("Bonferroni z = %.3f, N = 10,000\n" % z_b)
print("%-34s %12s %22s %24s" % ("strategy", "mean [s]", "CI [s]", "diff vs 1-stop [s]"))
for r_ in rows:
    print("%-34s %12.2f   [%9.2f, %9.2f]   %+7.2f [%+.2f, %+.2f]" % (r_["name"], r_["mean_s"], r_["ci_low_s"], r_["ci_high_s"], r_["diff_s"], r_["diff_low_s"], r_["diff_high_s"]))
vr = variance_reduction_ratio(best1, best2, p, 10_000, SEED + 33)
print("\nCRN variance reduction (independent / paired variance of the 2-stop minus 1-stop difference): %.1fx" % vr)
sd_D = np.std(X2[:, 1] - X2[:, 0], ddof=1)
print("Sample size for a +/-0.25 s half-width: n >= (z s_D / h)^2 = %.0f (we use 10,000)" % ((z_b * sd_D / 0.25) ** 2))
""")

md(r"""
### 6.3 How the answer changes with the SC onset probability $P_{GS}$
For each $P_{GS}$ in the sweep, 10,000 fresh common scenarios give paired differences (two-stop − one-stop, reactive − one-stop) with 95% CIs. The crossover is the $P_{GS}$ at which a difference changes sign (linear interpolation of the means). We also sweep $\alpha_{SC}$ at the baseline $P_{GS}$.
""")
code(r"""
sweep = []
for v in P_GS_SWEEP:
    q = with_params(p, p_gs=v)
    X = run_paired(SHORTLIST, q, 10_000, SEED + 100 + int(v * 1e4))
    sweep.append([v] + [mean_ci(X[:, j] - X[:, 0]) for j in (1, 2)])
def crossover(xs, ys):
    # first P_GS where the mean difference changes sign (linear interpolation)
    for x0, y0, x1, y1 in zip(xs, ys, xs[1:], ys[1:]):
        if y0 == 0:
            return x0
        if y0 * y1 < 0:
            return x0 + (x1 - x0) * y0 / (y0 - y1)
    return None
fig, ax = plt.subplots(figsize=(7, 4.2))
cross = {}
for j, lab in ((1, "two-stop − one-stop"), (2, "pit-if-neutralised − one-stop")):
    m = np.array([row[j][0] for row in sweep]); lo = np.array([row[j][1] for row in sweep]); hi = np.array([row[j][2] for row in sweep])
    ax.plot(P_GS_SWEEP, m, "o-", label=lab); ax.fill_between(P_GS_SWEEP, lo, hi, alpha=.25)
    cross[lab] = crossover(P_GS_SWEEP, m)
    print("%-32s" % lab, " ".join("%.3f:%+.2f[%+.2f,%+.2f]" % (v, a, b, c) for v, (a, b, c) in zip(P_GS_SWEEP, [row[j] for row in sweep])))
ax.axhline(0, color="k", lw=.8); ax.axvline(p["p_gs"], color="grey", ls=":", label="baseline $P_{GS}$")
ax.set_xlabel("$P_{GS}$ (per-lap Safety-Car onset probability)"); ax.set_ylabel("paired race-time difference [s]")
ax.set_title("Strategy difference vs SC onset probability (95% CI)"); ax.legend(); ax.grid(alpha=.3); fig.tight_layout()
fig.savefig(os.path.join(FIG_DIR, "results_pgs_sweep.png"), dpi=150); plt.show()
for k, v in cross.items():
    print("crossover (%s): %s" % (k, "P_GS ~ %.4f" % v if v is not None else "none in the swept range"))
""")

md(r"""
### 6.4 Sensitivity analysis (which inputs drive the answer?)
One-at-a-time sweeps of $P_{GS}$, $\alpha_{SC}$, minimum SC length $m$, crew-time spread $\sigma_C$ and the HARD wear rate. The reported quantity is the headline paired difference (two-stop − one-stop) with its 95% CI (4,000 common scenarios per point).
""")
code(r"""
SENS = {
    "p_gs":        [0.0, 0.02, 0.04, 0.06],
    "alpha_sc":    [0.25, 0.43, 0.60],
    "sc_min_laps": [2, 3, 4],
    "crew_sigma":  [0.3, 0.5, 0.8],
    "k_hard":      [0.025, 0.035, 0.050],
}
sens_rows = []
for name, values in SENS.items():
    for v in values:
        if name == "alpha_sc":
            q = with_params(p, alpha_sc=v, alpha_vsc=p["alpha_vsc"])
        elif name == "k_hard":
            ks = dict(p["k_s_per_lap"]); ks["HARD"] = v; q = with_params(p, k_s_per_lap=ks)
        else:
            q = with_params(p, **{name: v})
        X = run_paired(SHORTLIST[:2], q, 4000, SEED + 500)
        m, lo, hi = mean_ci(X[:, 1] - X[:, 0])
        sens_rows.append(dict(param=name, value=v, mean_diff_s=m, ci_low_s=lo, ci_high_s=hi))
fig, ax = plt.subplots(figsize=(7, 3.8))
for i, name in enumerate(SENS):
    rr = [r_ for r_ in sens_rows if r_["param"] == name]
    lo_, hi_ = min(r_["mean_diff_s"] for r_ in rr), max(r_["mean_diff_s"] for r_ in rr)
    ax.barh(i, hi_ - lo_, left=lo_, color="C0", alpha=.6)
    print("%-12s range of mean difference: %+.2f .. %+.2f s (swing %.2f s)" % (name, lo_, hi_, hi_ - lo_))
ax.set_yticks(range(len(SENS))); ax.set_yticklabels(list(SENS)); ax.axvline(0, color="k", lw=.8)
ax.set_xlabel("two-stop − one-stop mean difference [s]"); ax.set_title("Sensitivity (tornado)"); ax.grid(alpha=.3, axis="x")
fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "sensitivity_tornado.png"), dpi=150); plt.show()
"""
)

md(r"""
**Interaction of the two strongest drivers.** One-at-a-time sweeps can hide interactions, so the decision quantity *pit-if-neutralised − one-stop* is mapped over a $7\times 5$ grid of $P_{GS}$ and the HARD wear rate (3,000 common scenarios per cell). Cells whose 95% CI excludes zero are marked: ▼ reactive is significantly faster, ▲ significantly slower, · not distinguishable.
""")
code(r"""
pgs_g = np.array([0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]); kh_g = np.array([0.025, 0.030, 0.035, 0.045, 0.055])
M = np.zeros((len(kh_g), len(pgs_g))); S = np.zeros_like(M, dtype=int)
for i, kh in enumerate(kh_g):
    ks = dict(p["k_s_per_lap"]); ks["HARD"] = kh
    for j, v in enumerate(pgs_g):
        q = with_params(p, k_s_per_lap=ks, p_gs=v)
        X = run_paired([best1, bestR], q, 3000, SEED + 800)
        m, lo, hi = mean_ci(X[:, 1] - X[:, 0])
        M[i, j] = m; S[i, j] = -1 if hi < 0 else (1 if lo > 0 else 0)
fig, ax = plt.subplots(figsize=(7.5, 4.2))
lim = np.abs(M).max()
im = ax.imshow(M, origin="lower", cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
for i in range(len(kh_g)):
    for j in range(len(pgs_g)):
        ax.text(j, i, "%+.1f\n%s" % (M[i, j], {-1: "▼", 0: "·", 1: "▲"}[S[i, j]]), ha="center", va="center", fontsize=8)
ax.set_xticks(range(len(pgs_g))); ax.set_xticklabels(pgs_g); ax.set_yticks(range(len(kh_g))); ax.set_yticklabels(kh_g)
ax.set_xlabel("$P_{GS}$"); ax.set_ylabel("HARD wear rate $k_H$ [s/lap]"); ax.set_title("pit-if-neutralised − one-stop [s] (95% CI sign)")
fig.colorbar(im, ax=ax, label="mean paired difference [s]"); fig.tight_layout()
fig.savefig(os.path.join(FIG_DIR, "sensitivity_map.png"), dpi=150); plt.show()
print("reactive significantly faster in %d of %d cells" % ((S == -1).sum(), S.size))
""")

md(r"""
### 6.5 Performance: plain loop vs vectorised NumPy
The same scenarios are run through the per-race Python loop and the vectorised simulator. The results must be identical, and the timings are the median of 3 runs.

**Why it is faster.** The loop advances one race at a time, so every lap costs dozens of Python-level operations (dictionary look-ups, a scalar RK4 step, branching on the track status). The vectorised version swaps the loops: it advances *all* races one lap at a time, so each RK4 stage, each lap-time formula and each pit decision is one NumPy array operation running in compiled code. The Python overhead is paid 62 times per strategy instead of $62N$ times, so the speed-up grows with $N$ until memory bandwidth dominates. Pre-drawing every random number per source (status, lap noise, crew) also keeps CRN exact: the two implementations read the same numbers and agree to $10^{-9}$ s.
""")
code(r"""
scen = draw_scenarios(2000, p, SEED + 7)
t_loop, a = timed(lambda: np.array([simulate_race_loop(best1, p, scen, i) for i in range(2000)]))
t_vec, b = timed(lambda: simulate_scenarios(best1, p, scen))
assert np.max(np.abs(a - b)) < 1e-9
print("loop %.3f s | vectorised %.4f s | speed-up %.1fx (identical results)" % (t_loop, t_vec, t_loop / t_vec))

# scaling with the number of replications (median of 3 runs each)
Ns_perf = [250, 500, 1000, 2000, 4000, 8000]
t_l, t_v = [], []
for n in Ns_perf:
    sc_ = draw_scenarios(n, p, SEED + 70 + n)
    t_l.append(timed(lambda: [simulate_race_loop(best1, p, sc_, i) for i in range(n)])[0] if n <= 4000 else np.nan)
    t_v.append(timed(lambda: simulate_scenarios(best1, p, sc_))[0])
t_l, t_v = np.array(t_l), np.array(t_v)
ok = np.isfinite(t_l)
fig, axs = plt.subplots(1, 2, figsize=(11, 4))
axs[0].loglog(np.array(Ns_perf)[ok], t_l[ok], "o-", label="plain Python loop (one race at a time)")
axs[0].loglog(Ns_perf, t_v, "s-", label="vectorised NumPy (all races per lap step)")
axs[0].set_xlabel("races simulated"); axs[0].set_ylabel("wall time [s]"); axs[0].set_title("Run time vs number of races")
axs[0].legend(); axs[0].grid(True, which="both", alpha=.3)
axs[1].semilogx(np.array(Ns_perf)[ok], t_l[ok] / t_v[ok], "o-", color="C2")
axs[1].set_xlabel("races simulated"); axs[1].set_ylabel("speed-up (loop / vectorised)"); axs[1].set_title("Measured speed-up")
axs[1].grid(True, which="both", alpha=.3); fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "performance_scaling.png"), dpi=150); plt.show()
for n, a_, b_ in zip(Ns_perf, t_l, t_v):
    print("N = %5d  loop %s  vectorised %.4f s  -> %s races/s" % (n, "%.3f s" % a_ if a_ == a_ else "   (skipped)", b_, "{:,.0f}".format(n / b_)))
print("Stage-1 screening of %d strategies x 1,000 races would take ~%.0f s with the loop vs %.1f s vectorised"
      % (len(cands), len(cands) * t_l[2], len(cands) * t_v[2]))
""")


md(r"""
### 6.6 Team extension: is double-stacking under a Safety Car worth it?
When a Safety Car comes out, both cars of a team want the cheap stop, but the second car must queue behind the first in the single pit box. Three team policies are compared on the same 4,000 race scenarios (CRN across policies), using the best reactive one-stop from Stage 1:
* **both react**: both cars stop at the first SC/VSC in the window, so they double-stack whenever it happens (otherwise A stops on lap $L$ and B on $L+1$);
* **split**: car A reacts, car B keeps its fixed one-stop plan (staggered one lap after A's planned lap, as teams do to avoid a planned double-stack);
* **both fixed**: neither car reacts (A on lap $L$, B on lap $L+1$).

The output is the team's total race time (A + B) relative to *both fixed*, with 95% CIs, and car B's queueing delay. The sweep over $P_{GS}$ shows when a team should split its cars.
""")
code(r"""
react_ = bestR
fixed_ = strategy(react_["pit_laps"], react_["compounds"])
fixed_b = strategy([react_["pit_laps"][0] + 1], react_["compounds"])     # B staggered one lap to avoid a planned stack
react_b = strategy([react_["pit_laps"][0] + 1], react_["compounds"], reactive_window=(react_["reactive_window"][0], react_["pit_laps"][0] + 1))
policies = {"both react": (react_, react_b), "split (A reacts)": (react_, fixed_b), "both fixed": (fixed_, fixed_b)}
team_rows, team_sweep = {}, {k: [] for k in policies}
PGS_TEAM = [0.0, 0.02, 0.04, 0.06]
for v in PGS_TEAM:
    q = with_params(p, p_gs=v)
    res = {k: run_team(sa, sb, q, 4000, SEED + 600 + int(v * 1e4)) for k, (sa, sb) in policies.items()}
    base = res["both fixed"]["total_a"] + res["both fixed"]["total_b"]
    for k, R in res.items():
        team_sweep[k].append(mean_ci(R["total_a"] + R["total_b"] - base))
    if abs(v - p["p_gs"]) < 1e-12:
        team_rows = res
print("Baseline P_GS = %.3f, 4,000 common race scenarios per policy" % p["p_gs"])
for k, R in team_rows.items():
    w = R["stack_delay_b"]
    print("  %-18s car B waited in %.1f%% of races, mean wait when it did %.2f s; traffic %.2f s" %
          (k, 100 * (w > 0).mean(), w[w > 0].mean() if (w > 0).any() else 0.0, R["traffic_b"].mean()))
fig, axs = plt.subplots(1, 2, figsize=(11, 4))
for k in ("both react", "split (A reacts)"):
    m = np.array([x[0] for x in team_sweep[k]]); lo = np.array([x[1] for x in team_sweep[k]]); hi = np.array([x[2] for x in team_sweep[k]])
    axs[0].plot(PGS_TEAM, m, "o-", label=k); axs[0].fill_between(PGS_TEAM, lo, hi, alpha=.25)
    print("%-18s team gain vs both fixed: %s" % (k, "  ".join("%.2f:%+.2f[%+.2f,%+.2f]" % (v, *x) for v, x in zip(PGS_TEAM, team_sweep[k]))))
R_r, R_s = team_rows["both react"], team_rows["split (A reacts)"]
dd = mean_ci((R_r["total_a"] + R_r["total_b"]) - (R_s["total_a"] + R_s["total_b"]))
print("Double-stack vs split, team time (baseline): %+.2f s [%+.2f, %+.2f]" % dd)
axs[0].axhline(0, color="k", lw=.8); axs[0].set_xlabel("$P_{GS}$"); axs[0].set_ylabel("team time vs both fixed [s]")
axs[0].set_title("Team policy under Safety-Car risk (95% CI)"); axs[0].legend(); axs[0].grid(alpha=.3)
w = team_rows["both react"]["stack_delay_b"]
axs[1].hist(w[w > 0], bins=40, color="C1", alpha=.8)
axs[1].set_xlabel("car B queueing delay when double-stacked [s]"); axs[1].set_ylabel("races"); axs[1].set_title("Double-stack delay (both react, baseline)")
axs[1].grid(alpha=.3); fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "team_double_stack.png"), dpi=150); plt.show()
""")


md(r"""
### 6.7 Real-data grounding: calibration and held-out validation (Singapore 2008–2025)
The data are 16 Singapore races from Jolpica-F1 (lap times and pit stops) plus 2023–2025 stints, compounds, stationary times and race-control messages from OpenF1 (`data/`, CC BY-NC-SA 4.0). The calibration code (`src/calibrate.py`) is shown in the next cell. The public lap data has no status flag, so Green / VSC / SC is **inferred from the field's lap times**: a neutralised lap is more than 18% slower than Green pace, and a neutralised period is a Safety Car when the field closes up behind it (gaps < 1.5 s), otherwise a VSC. The classifier is checked against OpenF1's race-control messages.

Then: $\hat P$ by maximum likelihood from transition counts, a Beta posterior for $P_{GS}$, the phase-type SC duration law, the neutralised pace ratios $k_S,k_V$, the 2025 (80 km/h) Green pit loss and stationary-time law, the measured SC pit-loss discount $\alpha_{SC}$, and per-compound wear rates from 2023–2025 stints.

**Held-out validation:** wear rates fitted on 2023–2024 predict the 2025 stints; the SC duration law fitted on 2008–2017 is tested on 2018–2025 (KS, parametric bootstrap); and $P_{GS}$ from 2008–2017 predicts the number of SC onsets in 2018–2025.
""")
code("# src/calibrate.py (real-data calibration)\nimport csv, io, urllib.request\n" + CAL.split("import numpy as np", 1)[1].replace("    import f1sim as F\n", "").replace("F.default_params()", "default_params()"))
code(r"""
CAL = calibrate()
names = "GVS"
print("Inferred track status (G Green, V VSC, S Safety Car):")
for y in CAL["years"]:
    print("  %d  %s" % (y, "".join(names[s] for s in CAL["status"][y]["status"])))
print("\nCheck against OpenF1 race-control messages:")
for y, l, msg, st in CAL["race_control"]:
    print("  %d lap %2d  %-30s -> inferred %s" % (y, l, msg, STATUS_NAMES[st]))
rc = {(y, l): st for y, l, m, st in CAL["race_control"]}
assert rc[(2023, 20)] == SC and rc[(2023, 22)] == SC and rc[(2023, 44)] == VSC
assert all(not (s != GREEN).any() for y, s in ((y, CAL["status"][y]["status"]) for y in (2024, 2025)))   # no SC in 2024-25
C_, P_ = CAL["transition_counts"], CAL["P"]
print("\nTransition counts (rows from, cols to G/V/S):\n", C_)
print("MLE P:\n", P_.round(4))
assert np.allclose(P_, C_ / C_.sum(1, keepdims=True)) and np.allclose(P_.sum(1), 1)
k, n = CAL["onsets_sc"]; mpost, lo, hi = CAL["p_gs_posterior"]
print("P_GS: %d onsets / %d Green laps = %.4f; Beta posterior mean %.4f, 95%% interval [%.4f, %.4f] (assumed baseline %.3f)"
      % (k, n, k / n, mpost, lo, hi, p["p_gs"]))
print("Lap-1 Safety Cars: %d of %d races -> p1 = %.3f" % (CAL["lap1_sc"], CAL["n_races"], CAL["lap1_sc"] / CAL["n_races"]))
m_, pss_ = CAL["sc_fit"]
print("SC durations", sorted(CAL["sc_durations"].tolist()), "-> m = %d, p_SS = %.3f, E[D] = %.2f laps" % (m_, pss_, m_ + pss_ / (1 - pss_)))
print("Neutralised pace: k_SC = %.3f (%d laps), k_VSC = %.3f (%d laps)  [literature 1.60 / 1.40]"
      % (CAL["ratios"][SC][0], CAL["ratios"][SC][1], CAL["ratios"][VSC][0], CAL["ratios"][VSC][1]))
cr = CAL["crew"]
print("Stationary time 2025: %d stops, median %.2f s, shifted lognormal shift %.1f s, mu %.3f, sigma %.3f, mean %.2f s"
      % (len(cr["stops"]), np.median(cr["stops"]), cr["shift"], cr["mu"], cr["sigma"], cr["mean"]))
print("Green net pit loss 2025: median %.2f s over %d stops -> transit loss dT_G = %.2f s (assumed 21.0 s)"
      % (np.median(CAL["pit2025"]["green"]), len(CAL["pit2025"]["green"]), CAL["dT_G"]))
for r_ in CAL["sc_stop_years"]:
    print("  %d: Green stops %.1f s (n=%d), SC stops %.1f s (n=%d) -> alpha_SC = %.2f" % (r_["year"], r_["green_s"], r_["n_green"], r_["sc_s"], r_["n_sc"], r_["alpha_sc"]))
print("Measured alpha_SC (median over races) = %.2f vs geometry-derived baseline %.2f" % (CAL["alpha_sc"], p["alpha_sc"]))
for c_, (b_, se_, nl_, ns_) in CAL["wear_all"].items():
    print("Wear %-6s %.4f +/- %.4f s/lap (%d clean laps, %d stints) -> model k_c = %.4f (assumed %.3f)%s"
          % (c_, b_, se_, nl_, ns_, CAL["params"]["k_s_per_lap"][c_], p["k_s_per_lap"][c_],
             "" if ns_ >= MIN_STINTS else "  [< %d stints: scaled from MEDIUM with the assumed ratio]" % MIN_STINTS))
V = CAL["validation"]
print("\nHELD-OUT VALIDATION")
print("  2025 stints, lap-time RMSE: wear model %.3f s vs no-wear model %.3f s (%d laps, fitted on 2023-24)"
      % (V["heldout_wear_rmse_s"], V["heldout_no_wear_rmse_s"], V["heldout_wear_laps"]))
print("  SC durations 2018-25 vs law fitted on 2008-17 (m=%d, p_SS=%.2f): KS D = %.3f, bootstrap p = %.2f"
      % (*V["train_sc_fit"], V["heldout_sc_duration_ks"], V["heldout_sc_duration_ks_p"]))
print("  SC onsets 2018-25: observed %d, predicted %.1f from 2008-17, Poisson p = %.2f"
      % (V["heldout_sc_onsets_observed"], V["heldout_sc_onsets_expected"], V["heldout_sc_onsets_poisson_p"]))
assert V["heldout_wear_rmse_s"] < V["heldout_no_wear_rmse_s"]
assert V["heldout_sc_duration_ks_p"] > 0.05 and V["heldout_sc_onsets_poisson_p"] > 0.05
print("PASS 6.7 (calibration consistent with held-out data)")
""")
code(r"""
fig, axs = plt.subplots(2, 2, figsize=(12, 8))
ax = axs[0, 0]
grid_ = np.full((len(CAL["years"]), 62), np.nan)
for i, y in enumerate(CAL["years"]):
    s_ = CAL["status"][y]["status"]; grid_[i, :len(s_)] = s_
from matplotlib.colors import ListedColormap
ax.imshow(grid_, aspect="auto", cmap=ListedColormap(["#2ca02c", "#ffbf00", "#d62728"]), vmin=0, vmax=2, interpolation="nearest")
ax.set_yticks(range(len(CAL["years"]))); ax.set_yticklabels(CAL["years"], fontsize=7); ax.set_xlabel("lap")
ax.set_title("Inferred track status, Singapore (green / VSC amber / SC red)")
ax = axs[0, 1]
D_ = CAL["sc_durations"]; xs_ = np.arange(1, D_.max() + 3)
pmf_ = np.where(xs_ < m_, 0, (1 - pss_) * pss_ ** np.maximum(xs_ - m_, 0))
ax.bar(xs_ - 0.2, [(D_ == x).mean() for x in xs_], 0.4, label="observed (%d SCs)" % len(D_))
ax.bar(xs_ + 0.2, pmf_, 0.4, label="phase-type fit m=%d, $p_{SS}$=%.2f" % (m_, pss_))
ax.set_xlabel("Safety-Car length [laps]"); ax.set_ylabel("probability"); ax.set_title("SC duration law"); ax.legend()
ax = axs[1, 0]
fuel_slope = p["gamma_s_per_kg"] * p["burn_kg_per_lap"]
rows_ = CAL["wear_rows"]
for ci, c_ in enumerate(("SOFT", "MEDIUM", "HARD")):
    rr = [x for x in rows_ if x[2] == c_]
    by = {}
    for k_ in set(x[1] for x in rr):
        q_ = [x for x in rr if x[1] == k_]
        t_ = np.array([x[5] + fuel_slope * (x[4] - 1) for x in q_]); a_ = np.array([x[3] for x in q_])
        for aa, tt in zip(a_, t_ - (t_ - CAL["wear_all"][c_][0] * a_).mean()):
            by.setdefault(int(aa), []).append(tt)
    ages = sorted(a for a in by if len(by[a]) >= 4)
    ax.plot(ages, [np.mean(by[a]) for a in ages], "o", ms=3, color="C%d" % ci, alpha=.7, label="%s observed" % c_.lower())
    ax.plot(ages, [CAL["wear_all"][c_][0] * a for a in ages], "-", color="C%d" % ci)
ax.set_xlabel("tyre age [laps]"); ax.set_ylabel("fuel-corrected lap time, stint-centred [s]"); ax.set_title("Tyre wear, 2023–2025 clean laps (lines: fit)")
ax.legend(fontsize=8); ax.grid(alpha=.3)
ax = axs[1, 1]
st_ = cr["stops"]; xx = np.linspace(cr["shift"] + 0.01, st_.max() + 1, 300)
ax.hist(st_, bins=15, density=True, alpha=.6, label="2025 stationary times (n=%d)" % len(st_))
pdf_ = np.exp(-(np.log(xx - cr["shift"]) - cr["mu"]) ** 2 / (2 * cr["sigma"] ** 2)) / ((xx - cr["shift"]) * cr["sigma"] * np.sqrt(2 * np.pi))
ax.plot(xx, pdf_, "k-", label="shifted lognormal fit"); ax.set_xlabel("stationary time [s]"); ax.set_title("Pit-crew time"); ax.legend()
fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "calibration_real_data.png"), dpi=150); plt.show()
""")

md(r"""
### 6.8 The answer with calibrated parameters, and parameter uncertainty
The calibrated values replace the assumed ones (compound pace offsets, fuel and noise stay as before). Stage 1 and Stage 2 are re-run on fresh seeds, so the shortlist is chosen again in the calibrated world.

Then **parameter uncertainty is propagated** through the decision (X5): 300 parameter sets are drawn ($P_{GS}$ from its Beta posterior, each wear rate from $N(\hat k_c, \widehat{se}^2)$, $\alpha_{SC}$ resampled from the per-race estimates), and each set is evaluated on 2,000 paired races. The result is the probability that each plan is best once both race randomness and parameter uncertainty are counted.
""")
code(r"""
pc = with_params(p, **CAL["params"])
cands_c = candidate_strategies(pc) + [strategy([L], c, reactive_window=(12, L)) for c in (("MEDIUM", "HARD"), ("HARD", "MEDIUM"), ("SOFT", "HARD")) for L in range(14, 46, 2)]
ranked_c = screen(cands_c, pc, 1000, SEED + 211)
pick = lambda pred: next(s for m, s in ranked_c if pred(s))
SL_C = [pick(lambda s: len(s["pit_laps"]) == 1 and s["reactive_window"] is None), pick(lambda s: len(s["pit_laps"]) == 2),
        pick(lambda s: s["reactive_window"] is not None)]
rows_c, Xc = paired_table(SL_C, pc, 10_000, SEED + 222, ref=0, z=bonferroni_z(2))
print("Calibrated world (alpha_SC = %.2f, alpha_VSC = %.2f, dT_G = %.1f s, P_GS = %.4f):" % (pc["alpha_sc"], pc["alpha_vsc"], pc["dT_green_s"], pc["p_gs"]))
for r_ in rows_c:
    print("  %-34s mean %.2f s   diff vs one-stop %+6.2f s [%+.2f, %+.2f]" % (r_["name"], r_["mean_s"], r_["diff_s"], r_["diff_low_s"], r_["diff_high_s"]))

rng_u = np.random.default_rng(SEED + 300)
k_gs, n_gs = CAL["onsets_sc"]
alphas_obs = np.array([r_["alpha_sc"] for r_ in CAL["sc_stop_years"]])
U = []
for d in range(300):
    ks = dict(pc["k_s_per_lap"])
    m_mid_ = p["m0_kg"] - p["burn_kg_per_lap"] * p["n_laps"] / 2
    for c_, (b_, se_, _, ns_) in CAL["wear_all"].items():
        if ns_ >= MIN_STINTS:
            ks[c_] = max(1e-3, rng_u.normal(b_, se_)) / (1 + p["beta_per_kg"] * m_mid_)
    ks["SOFT"] = ks["MEDIUM"] * p["k_s_per_lap"]["SOFT"] / p["k_s_per_lap"]["MEDIUM"]
    q = with_params(pc, p_gs=float(rng_u.beta(1 + k_gs, 1 + n_gs - k_gs)), k_s_per_lap=ks,
                    alpha_sc=float(np.clip(np.median(rng_u.choice(alphas_obs, len(alphas_obs))), 0, 1)), alpha_vsc=pc["alpha_vsc"])
    X = run_paired(SL_C, q, 2000, SEED + 5000 + d)
    U.append(X.mean(0))
U = np.array(U)
best = np.bincount(U.argmin(1), minlength=3) / len(U)
for j, s in enumerate(SL_C):
    print("P(best) %-34s %.2f" % (s["name"], best[j]))
d1, d2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
print("two-stop - one-stop: median %+.2f s, 90%% interval [%+.2f, %+.2f]" % (np.median(d1), *np.quantile(d1, [.05, .95])))
print("reactive - one-stop: median %+.2f s, 90%% interval [%+.2f, %+.2f]" % (np.median(d2), *np.quantile(d2, [.05, .95])))
fig, ax = plt.subplots(figsize=(7, 4))
ax.hist(d1, bins=30, alpha=.6, label="two-stop − one-stop"); ax.hist(d2, bins=30, alpha=.6, label="pit-if-neutralised − one-stop")
ax.axvline(0, color="k", lw=.8); ax.set_xlabel("expected paired difference [s] for one parameter draw"); ax.set_ylabel("parameter draws")
ax.set_title("Decision under parameter uncertainty (300 draws × 2,000 races)"); ax.legend(); ax.grid(alpha=.3)
fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "uncertainty_propagation.png"), dpi=150); plt.show()

# where does the calibrated answer switch?
sw_c = []
for v in [0.0, 0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04]:
    X = run_paired(SL_C, with_params(pc, p_gs=v, alpha_sc=pc["alpha_sc"], alpha_vsc=pc["alpha_vsc"]), 10_000, SEED + 900 + int(v * 1e4))
    sw_c.append((v, mean_ci(X[:, 2] - X[:, 0]), mean_ci(X[:, 1] - X[:, 0])))
for v, r_, t_ in sw_c:
    print("calibrated P_GS = %.4f: reactive - one-stop %+.2f [%+.2f, %+.2f] s | two-stop - one-stop %+.2f [%+.2f, %+.2f] s" % (v, *r_, *t_))
cross_c = crossover([x[0] for x in sw_c], [x[1][0] for x in sw_c])
print("calibrated switch point (reactive vs one-stop): %s" % ("P_GS ~ %.4f" % cross_c if cross_c is not None else "none in range"))
""")

# ---------------------------------------------------------------------------
md(r"""
## 7. Discussion and limitations

*The numbers below come from the run above. Re-read them after changing parameters.*
""")
code(r"""
print("Answer to the question (baseline P_GS = %.3f):" % p["p_gs"])
for r_ in rows[1:]:
    verdict = "faster" if r_["diff_high_s"] < 0 else ("slower" if r_["diff_low_s"] > 0 else "not distinguishable")
    print("  %-34s %+.2f s [%+.2f, %+.2f] vs best one-stop -> %s" % (r_["name"], r_["diff_s"], r_["diff_low_s"], r_["diff_high_s"], verdict))
for k, v in cross.items():
    print("  switch point (%s): %s" % (k, "P_GS ~ %.4f" % v if v is not None else "none within P_GS in [0, 0.06]"))
print("  CRN variance reduction: %.1fx" % vr)
""")
md(r"""
**Team extension (§6.6).** When both cars stop under the same neutralisation, the second car loses about 3 s queueing in the box (crew time plus turnaround minus the gap). The SC discount on its stop is much larger, so double-stacking still beats leaving car B out, by the margin printed in §6.6. Both reactive team policies beat the fixed plans, and the advantage grows with $P_{GS}$.

**Real-data findings (§6.7–6.8).** The data confirm the baseline Safety-Car rate ($\hat P_{GS}\approx0.022$, 95% interval roughly 0.014–0.034, against an assumed 0.020) and the minimum SC length (2 laps, mean ≈ 3.7 laps), and the duration law and onset rate both pass their held-out tests on 2018–2025. Two inputs change materially. First, SC laps at Singapore run at about **1.38×** Green pace, not the 1.60× of the literature. Second, the **measured pit-loss discount under a Safety Car is about 0.86**, twice the 0.43 that the uniform-slowdown geometry predicts. A stop under SC costs only a few seconds because the pit-lane entry and exit are close to the SC queue. With that discount, *pit-if-neutralised* becomes the best plan in the calibrated world, about 4 s faster than the best one-stop with a CI far from zero, and it remains best in every one of 300 parameter draws. In the calibrated sweep the reactive plan wins across the whole range, even at $P_{GS}=0$, because VSC periods and lap-1 Safety Cars still occur. So at Singapore the question is no longer *whether* to react but how wide the window should be.

**Interpretation (baseline run, master seed 20251005; re-check the printed numbers if you change parameters).**
* **Fixed windows gain little from safety cars.** A planned stop falls under SC only with probability $p_S(L)$, a few percent per lap, so the expected discount per stop is small (§3.6). The stage-2 table shows the best one-stop ahead of the best two-stop by several seconds, with a CI far from zero.
* **More safety cars make the two-stop *worse*, not better.** SC laps cheapen stops (via $\alpha_{SC}$), but they also replace Green laps, where degradation costs time, and they slow tyre wear ($\varphi_S$). Fresh tyres are therefore worth less, and in this model the second effect dominates. So the two-stop never overtakes the one-stop in the swept range.
* **The value of an SC comes from reacting to it.** The pit-if-neutralised strategy's gap to the one-stop shrinks steadily as $P_{GS}$ grows. It crosses zero at the printed switch point, about twice the baseline onset rate.
* **What drives the answer:** the HARD wear rate and $P_{GS}$ dominate the tornado chart, while $\alpha_{SC}$ and the crew-time spread barely matter. Tyre wear and the SC discount are therefore the inputs that §6.7 calibrates from real data.
* **CRN is extremely effective here:** under H6, SC laps are identical for all strategies, so they cancel. The measured variance ratio is in the thousands, far beyond the ≥ 2 a generic model would give.

**Limitations.**
1. Single car: no track position, overtaking or traffic. At Singapore, track position matters a lot, and this model ignores it.
2. The objective is expected race time, not finishing position or points.
3. Track status is *inferred* from lap times (public lap data has no status flag). It matches OpenF1's race-control messages for 2023, but short VSC periods before 2015 cannot exist and edge laps are partial. Compound pace offsets, the fuel effect and the SOFT wear rate (too few soft stints) are still assumed.
4. A time-homogeneous incident rate after lap 1, and no VSC→SC escalation.
5. Pit losses assume the 2025 80 km/h pit-lane limit.
6. No weather, red flags, or slow-stop / unsafe-release events.
7. Sixteen races give about 19 SC onsets, so $P_{GS}$ is uncertain. This is why the Beta posterior is propagated through the decision (§6.8).
8. The team model has two cars and no other traffic, and the no-passing rule applies only between team-mates.

**Future work:** a Bellman (dynamic-programming) optimal reactive policy over (lap, status, tyre age, stops left); a full-field traffic model built on the team DES; per-team crew-time distributions; and an in-browser Pyodide build of the Python model.
""")

md(r"""
## 8. References
[1] A. Heilmeier, M. Graf, J. Betz and M. Lienkamp, "Application of Monte Carlo methods to consider probabilistic effects in a race simulation for circuit motorsport," *Appl. Sci.*, vol. 10, no. 12, 4229, 2020, doi: 10.3390/app10124229.
[2] A. Heilmeier, A. Thomaser, M. Graf and J. Betz, "Virtual Strategy Engineer: Using artificial neural networks for making race strategy decisions in circuit motorsport," *Appl. Sci.*, vol. 10, no. 21, 7805, 2020, doi: 10.3390/app10217805.
[3] J. Bekker and W. Lotz, "Planning Formula One race strategies using discrete-event simulation," *J. Oper. Res. Soc.*, vol. 60, no. 7, pp. 952–961, 2009.
[4] T. Tulabandhula and C. Rudin, "Tire changes, fresh air, and yellow flags: Challenges in predictive analytics for professional racing," *Big Data*, vol. 2, no. 2, pp. 97–112, 2014, doi: 10.1089/big.2014.0018.
[5] A. M. Law, *Simulation Modeling and Analysis*, 5th ed. McGraw-Hill, 2015.
[6] P. Glasserman, *Monte Carlo Methods in Financial Engineering*. Springer, 2003.
[7] FastF1 documentation. https://docs.fastf1.dev/
[8] GPblog, "Pit lane speed limit raised in Singapore for strategy options," Oct. 2025.
[9] Lights Out Blog, "Every Safety Car deployment at the Singapore Grand Prix."
""")

nb = dict(cells=cells, metadata=dict(kernelspec=dict(name="python3", display_name="Python 3", language="python"),
                                     language_info=dict(name="python"), colab=dict(provenance=[])),
          nbformat=4, nbformat_minor=5)
os.makedirs(os.path.join(ROOT, "notebook"), exist_ok=True)
out = os.path.join(ROOT, "notebook", "f1-pit-strategy-simulator.ipynb")
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print("wrote", out, "with", len(cells), "cells")
