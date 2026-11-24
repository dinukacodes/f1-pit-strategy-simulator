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

cells = []


def md(text):
    cells.append(dict(cell_type="markdown", id="c%02d" % len(cells), metadata={}, source=text.strip("\n")))


def code(text):
    cells.append(dict(cell_type="code", id="c%02d" % len(cells), metadata={}, execution_count=None, outputs=[], source=text.strip("\n")))


def module_sections(src):
    """Split f1sim.py into (title, code) blocks at its '# ----' section banners."""
    parts = re.split(r"\n# -{20,}\n# (.+)\n# -{20,}\n", src)
    head = parts[0]
    out = [("Module header and imports", head)]
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

### 3.8 Link to module topics
| Equation / algorithm | Module topic |
|---|---|
| Tyre-wear ODE, RK4 (and Euler/RK2 for comparison), error order $O(h^4)$ | Numerical ODE solvers (●) |
| Box–Muller normals; shifted-lognormal and DTMC sampling by inverse transform; KS tests | Input modelling and random variate generation (●) |
| Phase-type track-status chain, $p(\ell)=p(1)P^{\ell-1}$, $\pi=\pi P$, MLE of $P$ | Markov chains (DTMC) (○) |
| CRN paired differences, CIs, $O(N^{-1/2})$ convergence, sample-size formula | Monte Carlo and the law of large numbers (○) |
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
""")

md(r"""
### 6.5 Performance: plain loop vs vectorised NumPy
The same 2,000 scenarios are run through the per-race Python loop and the vectorised simulator. The results must be identical, and the timings are the median of 3 runs.
""")
code(r"""
scen = draw_scenarios(2000, p, SEED + 7)
t_loop, a = timed(lambda: np.array([simulate_race_loop(best1, p, scen, i) for i in range(2000)]))
t_vec, b = timed(lambda: simulate_scenarios(best1, p, scen))
assert np.max(np.abs(a - b)) < 1e-9
print("loop %.3f s | vectorised %.4f s | speed-up %.1fx (identical results)" % (t_loop, t_vec, t_loop / t_vec))
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
**Interpretation (baseline run, master seed 20251005; re-check the printed numbers if you change parameters).**
* **Fixed windows gain little from safety cars.** A planned stop falls under SC only with probability $p_S(L)$, a few percent per lap, so the expected discount per stop is small (§3.6). The stage-2 table shows the best one-stop ahead of the best two-stop by several seconds, with a CI far from zero.
* **More safety cars make the two-stop *worse*, not better.** SC laps cheapen stops (via $\alpha_{SC}$), but they also replace Green laps, where degradation costs time, and they slow tyre wear ($\varphi_S$). Fresh tyres are therefore worth less, and in this model the second effect dominates. So the two-stop never overtakes the one-stop in the swept range.
* **The value of an SC comes from reacting to it.** The pit-if-neutralised strategy's gap to the one-stop shrinks steadily as $P_{GS}$ grows. It crosses zero at the printed switch point, about twice the baseline onset rate.
* **What drives the answer:** the HARD wear rate and $P_{GS}$ dominate the tornado chart, while $\alpha_{SC}$ and the crew-time spread barely matter. Tyre wear is therefore the first parameter to calibrate with FastF1.
* **CRN is extremely effective here:** under H6, SC laps are identical for all strategies, so they cancel. The measured variance ratio is in the thousands, far beyond the ≥ 2 a generic model would give.

**Limitations.**
1. Single car: no track position, overtaking or traffic. At Singapore, track position matters a lot, and this model ignores it.
2. The objective is expected race time, not finishing position or points.
3. Parameters marked *assumed* (wear rates, pit geometry, crew spread) still need calibration with FastF1 data (`src/calibrate.py`).
4. A time-homogeneous incident rate after lap 1, and no VSC→SC escalation.
5. Pit losses assume the 2025 80 km/h pit-lane limit.
6. No weather, red flags, or slow-stop / unsafe-release events.
7. Only about six Singapore races exist in FastF1, so $P_{GS}$ is uncertain. Hence the sweep and the sensitivity study.

**With more time:** calibrate from FastF1, add a Bellman (dynamic-programming) optimal reactive policy, and extend to the two-car team model.
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
out = os.path.join(ROOT, "notebook", "f1_pit_strategy_simulator.ipynb")
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print("wrote", out, "with", len(cells), "cells")
