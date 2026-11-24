"""
f1sim - single-car Formula 1 pit-stop strategy simulator.

Model summary (see the notebook for derivations):
  * Tyre wear ODE per lap, solved with RK4:
        dw/dl = k_c * (1 + beta * m(l)) * (1 + eta * w) * phi(status)        [s/lap]
  * Fuel mass m(l) = m0 - b * (l - 1)                                         [kg]
  * Green lap time  t = t0 + offset_c + w + gamma * m + eps,  eps ~ N(0, sigma^2)
  * VSC / SC lap time t = k_s * t0  (set by the neutralisation, not the car)
  * Track status: lap-wise DTMC over {Green, VSC, SC_1..SC_m, SC+} (phase-type
    minimum Safety-Car length), separate lap-1 onset probability.
  * Pit loss on the in-lap: (1 - alpha_s) * dT_G + crew time, with
    alpha_s = (k_s - 1) * T_bypass / dT_G derived from pit-lane geometry and
    crew time ~ shifted lognormal.
  * Common random numbers: independent streams for status, lap noise and crew
    time (numpy SeedSequence), so every strategy sees the same race scenario.

Units: time in seconds [s], fuel in kilograms [kg], laps are 1-based integers.
Status codes: 0 = Green, 1 = VSC, 2 = SC.
"""

import copy
import math
import time

import numpy as np

GREEN, VSC, SC = 0, 1, 2
STATUS_NAMES = ("Green", "VSC", "SC")
DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def default_params():
    """Baseline parameter set for a 62-lap Singapore race.

    Every value is tagged in PARAM_SOURCES as 'literature', 'public data' or
    'assumed (calibrate with FastF1)'. Returns a new dict each call.
    """
    p = dict(
        n_laps=62,                      # [laps] 2025 Singapore race distance
        t0_s=96.0,                      # [s] base clean lap time, new tyre, no fuel
        offset_s={"SOFT": 0.0, "MEDIUM": 0.35, "HARD": 0.70},   # [s] compound pace offset
        k_s_per_lap={"SOFT": 0.100, "MEDIUM": 0.060, "HARD": 0.035},  # [s/lap] wear rate
        eta_per_s=0.02,                 # [1/s] wear self-acceleration (worn tyres wear faster)
        beta_per_kg=0.004,              # [1/kg] extra wear per kg of fuel
        m0_kg=100.0,                    # [kg] start fuel
        burn_kg_per_lap=1.6,            # [kg/lap] fuel burn
        gamma_s_per_kg=0.03,            # [s/kg] lap-time penalty per kg of fuel
        sigma_s=0.35,                   # [s] lap-time noise standard deviation
        # neutralisations
        k_vsc=1.40,                     # [-] VSC lap time / reference lap time
        k_sc=1.60,                      # [-] SC lap time / reference lap time
        phi_vsc=0.50,                   # [-] tyre-wear factor under VSC
        phi_sc=0.25,                    # [-] tyre-wear factor under SC
        # Markov chain (per-lap probabilities)
        p_gv=0.012,                     # [-] Green -> VSC onset
        p_gs=0.020,                     # [-] Green -> SC onset
        p_lap1_sc=0.15,                 # [-] SC onset on lap 1 (start incidents)
        p_vv=0.60,                      # [-] VSC persistence
        sc_min_laps=3,                  # [laps] minimum Safety-Car length m
        p_ss=0.50,                      # [-] SC persistence after the minimum
        # pit lane geometry (2025, 80 km/h limit)
        t_pit_s=36.0,                   # [s] pit entry -> exit through the lane (incl. no stop)
        t_bypass_s=15.0,                # [s] same section driven on track at racing speed
        # stationary crew time T = shift + exp(mu + sigma * Z)
        crew_shift_s=2.0,               # [s] physical minimum stop
        crew_mu=-0.51,                  # [-] log-scale location (median extra ~0.6 s)
        crew_sigma=0.50,                # [-] log-scale spread
        random=True,                    # False -> deterministic benchmark mode
    )
    return derive_alphas(p)


PARAM_SOURCES = {
    "n_laps": "public data (2025 race report)",
    "k_vsc, k_sc": "literature (Heilmeier et al. 2020, ~140% / ~160%)",
    "phi_vsc, phi_sc": "literature (Heilmeier et al. 2020, tyre ageing -50% / -75%)",
    "p_gs, p_gv, p_lap1_sc": "public data, rough (~7 SC onsets in ~370 laps, 2018-2025); calibrate with FastF1",
    "t_pit_s, t_bypass_s": "assumed (calibrate with FastF1 2025 PitInTime/PitOutTime)",
    "crew_*": "assumed, informed by published stationary times (DHL)",
    "t0_s, offset_s, k_s_per_lap, eta, beta, gamma, sigma": "assumed (calibrate with FastF1 clean stints)",
}


def derive_alphas(p):
    """Derive VSC/SC net-transit-loss reductions from pit-lane geometry.

    dT_G = T_pit - T_bypass; under neutralisation the bypassed section takes
    k_s * T_bypass while the speed-limited lane is unchanged, so
    alpha_s = (k_s - 1) * T_bypass / dT_G.  Modifies and returns p.
    """
    d_green = p["t_pit_s"] - p["t_bypass_s"]          # [s]
    assert d_green > 0, "pit lane must be slower than the track"
    p["dT_green_s"] = d_green
    p["alpha_vsc"] = (p["k_vsc"] - 1.0) * p["t_bypass_s"] / d_green
    p["alpha_sc"] = (p["k_sc"] - 1.0) * p["t_bypass_s"] / d_green
    return p


def with_params(p, **changes):
    """Return a deep copy of p with changes applied (alphas re-derived unless overridden)."""
    q = copy.deepcopy(p)
    q.update(changes)
    if "alpha_sc" not in changes and "alpha_vsc" not in changes:
        derive_alphas(q)
    return q


# ---------------------------------------------------------------------------
# Numerical ODE solvers
# ---------------------------------------------------------------------------

def euler_solve(f, y0, t0, t1, n_steps):
    """Forward Euler: returns y(t1) after n_steps equal steps (global error O(h))."""
    h = (t1 - t0) / n_steps
    y = np.asarray(y0, dtype=float) if np.ndim(y0) else float(y0)
    t = t0
    for _ in range(n_steps):
        y = y + h * f(t, y)
        t += h
    return y


def rk2_solve(f, y0, t0, t1, n_steps):
    """Midpoint RK2: returns y(t1) (global error O(h^2))."""
    h = (t1 - t0) / n_steps
    y = np.asarray(y0, dtype=float) if np.ndim(y0) else float(y0)
    t = t0
    for _ in range(n_steps):
        k1 = f(t, y)
        k2 = f(t + h / 2, y + h / 2 * k1)
        y = y + h * k2
        t += h
    return y


def rk4_step(f, t, y, h):
    """One classical RK4 step of size h (local error O(h^5))."""
    k1 = f(t, y)
    k2 = f(t + h / 2, y + h / 2 * k1)
    k3 = f(t + h / 2, y + h / 2 * k2)
    k4 = f(t + h, y + h * k3)
    return y + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)


def rk4_solve(f, y0, t0, t1, n_steps):
    """Classical RK4: returns y(t1) (global error O(h^4)). y0 may be a float or array."""
    h = (t1 - t0) / n_steps
    y = np.asarray(y0, dtype=float) if np.ndim(y0) else float(y0)
    t = t0
    for _ in range(n_steps):
        y = rk4_step(f, t, y, h)
        t += h
    return y


def wear_rhs(p, compound, race_lap0, phi):
    """Right-hand side dw/da of the tyre-wear ODE for one lap.

    a is lap time-like (age measured in laps), race_lap0 is the race lap at
    a = 0 of this step, phi is the neutralisation factor. Works on arrays.
    Returns f(a, w) in [s/lap].
    """
    k = p["k_s_per_lap"][compound]
    beta, eta = p["beta_per_kg"], p["eta_per_s"]
    m0, b = p["m0_kg"], p["burn_kg_per_lap"]

    def f(a, w):
        fuel_kg = m0 - b * (race_lap0 - 1 + a)
        return k * (1.0 + beta * fuel_kg) * (1.0 + eta * w) * phi
    return f


def wear_closed_form(p, compound, stint_start_lap, age_laps, phi=1.0):
    """Exact solution of the wear ODE for constant phi (verification reference).

    w(a) = (exp(eta * k * phi * A(a)) - 1) / eta,
    A(a) = (1 + beta*(m0 - b*(s-1))) * a - beta*b*a^2/2.   Returns w [s].
    """
    k = p["k_s_per_lap"][compound]
    beta, eta = p["beta_per_kg"], p["eta_per_s"]
    m0, b = p["m0_kg"], p["burn_kg_per_lap"]
    a = np.asarray(age_laps, dtype=float)
    A = (1 + beta * (m0 - b * (stint_start_lap - 1))) * a - beta * b * a ** 2 / 2
    if eta == 0:
        return k * phi * A
    return (np.exp(eta * k * phi * A) - 1.0) / eta


# ---------------------------------------------------------------------------
# Random variate generation
# ---------------------------------------------------------------------------

def box_muller(n, rng):
    """n standard normals from uniforms by the Box-Muller transform."""
    m = (n + 1) // 2
    u1 = 1.0 - rng.random(m)            # in (0, 1], avoids log(0)
    u2 = rng.random(m)
    r = np.sqrt(-2.0 * np.log(u1))
    z = np.concatenate([r * np.cos(2 * np.pi * u2), r * np.sin(2 * np.pi * u2)])
    return z[:n]


def box_muller_from_uniforms(u1, u2):
    """Box-Muller on given uniform arrays (u1 in (0, 1]). Returns (z1, z2)."""
    r = np.sqrt(-2.0 * np.log(u1))
    return r * np.cos(2 * np.pi * u2), r * np.sin(2 * np.pi * u2)


def crew_time_params(p):
    """(shift [s], mu, sigma) of the shifted-lognormal stationary crew time."""
    return p["crew_shift_s"], p["crew_mu"], p["crew_sigma"]


def crew_time_from_normal(z, p):
    """Map standard normals z to stationary crew times [s] (exact inverse transform)."""
    return p["crew_shift_s"] + np.exp(p["crew_mu"] + p["crew_sigma"] * z)


def sample_crew_time(n, p, rng):
    """n stationary crew times [s] from the shifted lognormal."""
    return crew_time_from_normal(box_muller(n, rng), p)


# ---------------------------------------------------------------------------
# Track-status Markov chain
# ---------------------------------------------------------------------------

def lumped_matrix(p):
    """3x3 matrix over (Green, VSC, SC) with the same mean sojourn times.

    Used for reporting and for the stationarity check; the simulator uses the
    expanded phase-type chain from expanded_matrix().
    """
    a, c = p["p_gv"], p["p_gs"]
    mean_sc = sc_mean_duration(p)                       # [laps]
    r_sc = 1.0 / mean_sc
    return np.array([[1 - a - c, a, c],
                     [1 - p["p_vv"], p["p_vv"], 0.0],
                     [r_sc, 0.0, 1 - r_sc]])


def expanded_matrix(p):
    """Phase-type chain: states [G, V, SC_1..SC_m, SC+].

    SC_i -> SC_{i+1} with probability 1 enforces a minimum length m; SC_m and
    SC+ continue with p_ss or return to Green. Returns (P, collapse) where
    collapse[i] maps an expanded state to 0/1/2.
    """
    m = int(p["sc_min_laps"])
    n = 2 + m + 1
    P = np.zeros((n, n))
    a, c = p["p_gv"], p["p_gs"]
    P[0, 0], P[0, 1], P[0, 2] = 1 - a - c, a, c
    P[1, 0], P[1, 1] = 1 - p["p_vv"], p["p_vv"]
    for i in range(m - 1):
        P[2 + i, 3 + i] = 1.0
    last = 2 + m - 1
    for s in (last, n - 1):
        P[s, n - 1] = p["p_ss"]
        P[s, 0] = 1 - p["p_ss"]
    collapse = np.array([0, 1] + [2] * (m + 1))
    assert P.min() >= 0 and np.allclose(P.sum(1), 1.0)
    return P, collapse


def lap1_row(p):
    """Distribution of the expanded state on lap 1 (start from the grid in Green)."""
    P, _ = expanded_matrix(p)
    row = np.zeros(P.shape[0])
    q = p["p_lap1_sc"]
    row[0] = 1 - q - p["p_gv"]
    row[1] = p["p_gv"]
    row[2] = q
    return row


def sc_mean_duration(p):
    """E[D_SC] = m + p_ss / (1 - p_ss) laps (phase-type minimum + geometric tail)."""
    return p["sc_min_laps"] + p["p_ss"] / (1 - p["p_ss"])


def stationary_distribution(P):
    """Solve pi = pi P, sum(pi) = 1 by least squares on the augmented system."""
    n = P.shape[0]
    A = np.vstack([P.T - np.eye(n), np.ones(n)])
    b = np.zeros(n + 1)
    b[-1] = 1.0
    return np.linalg.lstsq(A, b, rcond=None)[0]


def renewal_fractions(p):
    """Closed-form long-run fractions (Green, VSC, SC) when neutralisations end in Green.

    pi_G = 1 / (1 + a E[D_V] + c E[D_S]), pi_V = a E[D_V] pi_G, pi_S = c E[D_S] pi_G.
    """
    ev = 1.0 / (1 - p["p_vv"])
    es = sc_mean_duration(p)
    g = 1.0 / (1 + p["p_gv"] * ev + p["p_gs"] * es)
    return np.array([g, p["p_gv"] * ev * g, p["p_gs"] * es * g])


def sample_next_state(cum_rows, state, u):
    """Inverse-transform step for a DTMC, vectorised over replications."""
    c = cum_rows[state]                                   # (n, k) cumulative rows
    nxt = (u[:, None] > c).sum(axis=1)
    return np.minimum(nxt, c.shape[1] - 1)


def simulate_track_status(P, n_steps, rng, start=0):
    """Simulate a DTMC path of n_steps from matrix P by inverse transform."""
    P = np.asarray(P, dtype=float)
    cum = np.cumsum(P, axis=1)
    u = rng.random(n_steps)
    out = np.empty(n_steps, dtype=int)
    s = start
    for i in range(n_steps):
        out[i] = s
        s = min(int(np.searchsorted(cum[s], u[i], side="right")), P.shape[0] - 1)
    return out


def status_probabilities(p):
    """Exact marginal P(status on lap l) for l = 1..N, shape (N, 3)."""
    P, collapse = expanded_matrix(p)
    row = lap1_row(p)
    out = np.zeros((p["n_laps"], 3))
    for l in range(p["n_laps"]):
        for s in range(3):
            out[l, s] = row[collapse == s].sum()
        row = row @ P
    return out


def mle_transition_matrix(counts):
    """Maximum-likelihood transition matrix: row-normalised transition counts."""
    C = np.asarray(counts, dtype=float)
    return C / np.maximum(C.sum(axis=1, keepdims=True), 1.0)


def beta_interval(successes, trials, level=0.95, prior=(1.0, 1.0), n_draws=200000, seed=0):
    """Posterior mean and equal-tailed credible interval for a Bernoulli probability."""
    rng = np.random.default_rng(seed)
    a, b = prior[0] + successes, prior[1] + trials - successes
    draws = rng.beta(a, b, n_draws)
    lo, hi = np.quantile(draws, [(1 - level) / 2, (1 + level) / 2])
    return a / (a + b), lo, hi


def mle_sc_persistence(durations, m=None):
    """Phase-type SC fit: m = min duration, p_ss = sum(D-m) / sum(D-m+1)."""
    d = np.asarray(durations, dtype=float)
    m = int(d.min()) if m is None else m
    ex = d - m
    return m, ex.sum() / (ex + 1).sum()


# ---------------------------------------------------------------------------
# Pit loss
# ---------------------------------------------------------------------------

def pit_loss(state, crew_time_s, p):
    """Total time lost on the in-lap for one stop [s].

    (1 - alpha_state) * dT_G + crew time; the stationary time is never scaled.
    Works with scalar or array state / crew time.
    """
    alpha = np.choose(np.asarray(state), [0.0, p["alpha_vsc"], p["alpha_sc"]])
    return (1.0 - alpha) * p["dT_green_s"] + crew_time_s


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def strategy(pit_laps, compounds, reactive_window=None, name=None):
    """Build a strategy dict.

    pit_laps: planned in-laps, compounds: one per stint. reactive_window=(a, b)
    makes the FIRST stop move earlier to the first lap in [a, b] that is under
    VSC/SC (pit if neutralised).
    """
    s = dict(pit_laps=list(pit_laps), compounds=list(compounds), reactive_window=reactive_window)
    if name is None:
        name = "%d-stop %s @%s%s" % (len(pit_laps), "-".join(c[0] for c in compounds),
                                     ",".join(str(l) for l in pit_laps),
                                     "" if reactive_window is None else " react[%d-%d]" % tuple(reactive_window))
    s["name"] = name
    return s


def validate_strategy(s, p):
    """True if the strategy is legal: >= 2 dry compounds, increasing in-laps inside the race."""
    laps, comps = s["pit_laps"], s["compounds"]
    n = p["n_laps"]
    if len(comps) != len(laps) + 1 or len(laps) == 0:
        return False
    if any(c not in DRY_COMPOUNDS for c in comps) or len(set(comps)) < 2:
        return False
    if any(not (1 <= l <= n - 1) for l in laps) or any(b <= a for a, b in zip(laps, laps[1:])):
        return False
    w = s.get("reactive_window")
    if w is not None:
        if not (1 <= w[0] <= w[1] <= laps[0]):
            return False
    return True


# ---------------------------------------------------------------------------
# Scenarios (common random numbers) and the race simulator
# ---------------------------------------------------------------------------

MAX_STOPS = 3


def draw_scenarios(n_reps, p, seed):
    """Draw n_reps race scenarios from three independent streams.

    Returns dict with 'status' (n, N) int, 'z_lap' (n, N) lap-noise normals and
    'z_crew' (n, MAX_STOPS) normals for crew times. The same scenarios are
    re-used for every strategy (common random numbers).
    """
    N = p["n_laps"]
    ss_status, ss_noise, ss_crew = np.random.SeedSequence(seed).spawn(3)
    g_status = np.random.default_rng(ss_status)
    g_noise = np.random.default_rng(ss_noise)
    g_crew = np.random.default_rng(ss_crew)

    if p.get("random", True):
        P, collapse = expanded_matrix(p)
        cum = np.cumsum(P, axis=1)
        u = g_status.random((n_reps, N))
        cum1 = np.cumsum(lap1_row(p))
        state = np.minimum((u[:, 0][:, None] > cum1[None, :]).sum(1), P.shape[0] - 1)
        status = np.empty((n_reps, N), dtype=np.int8)
        status[:, 0] = collapse[state]
        for l in range(1, N):
            state = sample_next_state(cum, state, u[:, l])
            status[:, l] = collapse[state]
        z_lap = box_muller(n_reps * N, g_noise).reshape(n_reps, N)
        z_crew = box_muller(n_reps * MAX_STOPS, g_crew).reshape(n_reps, MAX_STOPS)
    else:
        status = np.zeros((n_reps, N), dtype=np.int8)
        z_lap = np.zeros((n_reps, N))
        z_crew = np.zeros((n_reps, MAX_STOPS))
    return dict(status=status, z_lap=z_lap, z_crew=z_crew)


def _first_stop_laps(s, status):
    """Actual first in-lap per replication, applying the reactive rule if any."""
    n = status.shape[0]
    first = np.full(n, s["pit_laps"][0], dtype=int)
    w = s.get("reactive_window")
    if w is not None:
        a, b = w
        seg = status[:, a - 1:b] != GREEN                 # laps a..b
        hit = seg.any(axis=1)
        first[hit] = a + seg[hit].argmax(axis=1)
    return first


def simulate_scenarios(s, p, scen, return_details=False):
    """Vectorised race simulation of strategy s over all scenarios.

    Returns total race times [s] (n,), or a dict of per-lap arrays when
    return_details=True.
    """
    status = scen["status"]
    n, N = status.shape
    noise_sd = p["sigma_s"] if p.get("random", True) else 0.0
    crew = crew_time_from_normal(scen["z_crew"], p) if p.get("random", True) else \
        np.full((n, MAX_STOPS), p["crew_shift_s"] + math.exp(p["crew_mu"]))

    first = _first_stop_laps(s, status)
    later = np.array(s["pit_laps"][1:], dtype=int)
    stint = np.zeros(n, dtype=int)
    w = np.zeros(n)                                       # [s] tyre degradation
    age = np.zeros(n)                                     # [laps]
    comps = s["compounds"]
    lap_t = np.zeros((n, N))
    if return_details:
        fuel_hist, age_hist, w_hist = np.zeros((n, N)), np.zeros((n, N)), np.zeros((n, N))
    phi_of = np.array([1.0, p["phi_vsc"], p["phi_sc"]])
    k_of = np.array([1.0, p["k_vsc"], p["k_sc"]])
    pit_laps_taken = [[] for _ in range(n)] if return_details else None

    for l in range(1, N + 1):
        st = status[:, l - 1]
        fuel = p["m0_kg"] - p["burn_kg_per_lap"] * (l - 1)          # [kg]
        offset = np.array([p["offset_s"][c] for c in comps])[stint]
        green_t = p["t0_s"] + offset + w + p["gamma_s_per_kg"] * fuel + noise_sd * scen["z_lap"][:, l - 1]
        t = np.where(st == GREEN, green_t, k_of[st] * p["t0_s"])
        if return_details:
            fuel_hist[:, l - 1], age_hist[:, l - 1], w_hist[:, l - 1] = fuel, age, w
        # integrate wear over this lap (one RK4 step of 1 lap, per compound)
        phi = phi_of[st]
        new_w = np.empty(n)
        for ci, c in enumerate(comps):
            idx = stint == ci
            if idx.any():
                f = wear_rhs(p, c, l, phi[idx])
                new_w[idx] = rk4_step(f, 0.0, w[idx], 1.0)
        w, age = new_w, age + 1
        # pit stop on this in-lap?
        stop = np.where(stint == 0, first == l, False)
        if len(later):
            for j, L in enumerate(later):
                stop |= (stint == j + 1) & (l == L)
        if stop.any():
            idx = np.nonzero(stop)[0]
            t[idx] += pit_loss(st[idx], crew[idx, stint[idx]], p)
            stint[idx] += 1
            w[idx], age[idx] = 0.0, 0.0
            if return_details:
                for i in idx:
                    pit_laps_taken[i].append(l)
        lap_t[:, l - 1] = t
    total = lap_t.sum(axis=1)
    if not return_details:
        return total
    return dict(total_time=total, lap_times=lap_t, status=status, fuel_kg=fuel_hist,
                tyre_age=age_hist, wear_s=w_hist, pit_laps=pit_laps_taken)


def simulate_race(s, p, seed):
    """One race for one strategy (scenario derived from seed). Returns a dict of arrays."""
    d = simulate_scenarios(s, p, draw_scenarios(1, p, seed), return_details=True)
    return dict(total_time=float(d["total_time"][0]), lap_times=d["lap_times"][0],
                status=d["status"][0].astype(int), fuel_kg=d["fuel_kg"][0],
                tyre_age=d["tyre_age"][0], pit_laps=d["pit_laps"][0])


def run_paired(strategies, p, n_reps, seed):
    """Total race times (n_reps, n_strategies) with every scenario re-used (CRN)."""
    scen = draw_scenarios(n_reps, p, seed)
    return np.column_stack([simulate_scenarios(s, p, scen) for s in strategies])


def simulate_race_loop(s, p, scen, i):
    """Plain-Python single-replication simulator (baseline for the speed-up study).

    Uses scenario row i, so it must reproduce simulate_scenarios exactly.
    """
    N = p["n_laps"]
    status = scen["status"][i]
    first = int(_first_stop_laps(s, scen["status"][i:i + 1])[0])
    stops = [first] + list(s["pit_laps"][1:])
    stint, w, total = 0, 0.0, 0.0
    phi_of = (1.0, p["phi_vsc"], p["phi_sc"])
    k_of = (1.0, p["k_vsc"], p["k_sc"])
    rand = p.get("random", True)
    for l in range(1, N + 1):
        st = int(status[l - 1])
        c = s["compounds"][stint]
        fuel = p["m0_kg"] - p["burn_kg_per_lap"] * (l - 1)
        if st == GREEN:
            t = p["t0_s"] + p["offset_s"][c] + w + p["gamma_s_per_kg"] * fuel
            if rand:
                t += p["sigma_s"] * scen["z_lap"][i, l - 1]
        else:
            t = k_of[st] * p["t0_s"]
        w = float(rk4_step(wear_rhs(p, c, l, phi_of[st]), 0.0, w, 1.0))
        if stint < len(stops) and l == stops[stint]:
            z = scen["z_crew"][i, stint]
            crew = p["crew_shift_s"] + math.exp(p["crew_mu"] + p["crew_sigma"] * z) if rand \
                else p["crew_shift_s"] + math.exp(p["crew_mu"])
            t += float(pit_loss(st, crew, p))
            stint += 1
            w = 0.0
        total += t
    return total


# ---------------------------------------------------------------------------
# Analytic results (verification references)
# ---------------------------------------------------------------------------

def linear_params(p):
    """Copy of p reduced to the analytically tractable case: eta = beta = 0, phi = 1."""
    return with_params(p, eta_per_s=0.0, beta_per_kg=0.0, phi_vsc=1.0, phi_sc=1.0)


def green_total_linear(s, p):
    """Exact deterministic Green race time for linear wear (eta = beta = 0), no pit loss.

    Stint of length S on compound c costs S*offset_c + k_c * S(S-1)/2 plus the
    strategy-independent base and fuel terms.
    """
    N = p["n_laps"]
    edges = [0] + list(s["pit_laps"]) + [N]
    base = N * p["t0_s"] + p["gamma_s_per_kg"] * sum(p["m0_kg"] - p["burn_kg_per_lap"] * (l - 1) for l in range(1, N + 1))
    tot = base
    for c, (a, b) in zip(s["compounds"], zip(edges, edges[1:])):
        S = b - a
        tot += S * p["offset_s"][c] + p["k_s_per_lap"][c] * S * (S - 1) / 2
    return tot


def optimal_one_stop_lap(c1, c2, p):
    """L* = [k2 N + (d2 - d1) + (k1 - k2)/2] / (k1 + k2) for the linear model (continuous)."""
    k1, k2 = p["k_s_per_lap"][c1], p["k_s_per_lap"][c2]
    d1, d2 = p["offset_s"][c1], p["offset_s"][c2]
    return (k2 * p["n_laps"] + (d2 - d1) + (k1 - k2) / 2) / (k1 + k2)


def two_stop_break_even_k(p):
    """Green break-even wear rate for 1 vs 2 equal stints: k N^2 / 12 = dT_G + E[crew]."""
    mean_crew = p["crew_shift_s"] + math.exp(p["crew_mu"] + p["crew_sigma"] ** 2 / 2)
    return 12 * (p["dT_green_s"] + mean_crew) / p["n_laps"] ** 2


def exact_expected_total(s, p):
    """Exact E[total race time] for a FIXED strategy in the linear case (eta=beta=0, phi=1).

    Uses the exact lap-status marginals from the Markov chain: SC/VSC laps take
    k_s * t0, Green laps the deterministic Green time, and each stop costs the
    expected pit loss for the status of its in-lap.
    """
    assert s.get("reactive_window") is None
    N = p["n_laps"]
    probs = status_probabilities(p)                       # (N, 3)
    mean_crew = p["crew_shift_s"] + math.exp(p["crew_mu"] + p["crew_sigma"] ** 2 / 2)
    edges = [0] + list(s["pit_laps"]) + [N]
    total = 0.0
    for c, (a, b) in zip(s["compounds"], zip(edges, edges[1:])):
        for l in range(a + 1, b + 1):
            age = l - a - 1
            green = p["t0_s"] + p["offset_s"][c] + p["k_s_per_lap"][c] * age + \
                p["gamma_s_per_kg"] * (p["m0_kg"] - p["burn_kg_per_lap"] * (l - 1))
            pr = probs[l - 1]
            total += pr[0] * green + pr[1] * p["k_vsc"] * p["t0_s"] + pr[2] * p["k_sc"] * p["t0_s"]
    for L in s["pit_laps"]:
        pr = probs[L - 1]
        total += mean_crew + p["dT_green_s"] * (pr[0] + pr[1] * (1 - p["alpha_vsc"]) + pr[2] * (1 - p["alpha_sc"]))
    return total


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

def mean_ci(x, level=0.95, z=None):
    """Mean and normal-approximation CI (z = 1.96 for 95% unless given)."""
    x = np.asarray(x, dtype=float)
    z = 1.959964 if z is None else z
    h = z * x.std(ddof=1) / math.sqrt(len(x))
    return x.mean(), x.mean() - h, x.mean() + h


def bonferroni_z(n_comparisons, level=0.95):
    """Two-sided normal quantile for a Bonferroni-adjusted family-wise level."""
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - (1 - level) / (2 * n_comparisons))


def candidate_strategies(p):
    """Screening grid of legal one-stop and two-stop strategies."""
    N = p["n_laps"]
    out = []
    for c in (("MEDIUM", "HARD"), ("HARD", "MEDIUM"), ("SOFT", "HARD")):
        for L in range(10, N - 9, 2):
            out.append(strategy([L], c))
    for c in (("SOFT", "MEDIUM", "HARD"), ("MEDIUM", "HARD", "SOFT"), ("MEDIUM", "MEDIUM", "HARD")):
        for L1 in range(10, 32, 3):
            for L2 in range(L1 + 12, N - 7, 3):
                out.append(strategy([L1, L2], c))
    return out


def screen(cands, p, n_reps, seed):
    """Stage 1: mean race time of every candidate on common scenarios. Returns sorted list."""
    scen = draw_scenarios(n_reps, p, seed)
    res = [(simulate_scenarios(s, p, scen).mean(), s) for s in cands]
    res.sort(key=lambda r: r[0])
    return res


def paired_table(strats, p, n_reps, seed, ref=0, z=None):
    """Stage 2: mean and CI of every strategy, and paired differences vs strategy `ref`."""
    X = run_paired(strats, p, n_reps, seed)
    rows = []
    for j, s in enumerate(strats):
        m, lo, hi = mean_ci(X[:, j], z=z)
        dm, dlo, dhi = mean_ci(X[:, j] - X[:, ref], z=z) if j != ref else (0.0, 0.0, 0.0)
        rows.append(dict(name=s["name"], mean_s=m, ci_low_s=lo, ci_high_s=hi,
                         diff_s=dm, diff_low_s=dlo, diff_high_s=dhi))
    return rows, X


def variance_reduction_ratio(sA, sB, p, n_reps, seed):
    """Var(independent difference) / Var(CRN paired difference)."""
    X = run_paired([sA, sB], p, n_reps, seed)
    a = run_paired([sA], p, n_reps, seed + 1)[:, 0]
    b = run_paired([sB], p, n_reps, seed + 2)[:, 0]
    return np.var(a - b, ddof=1) / np.var(X[:, 0] - X[:, 1], ddof=1)


def timed(fn, *args, repeat=3):
    """Median wall time [s] of fn(*args) over `repeat` runs, and its last result."""
    ts, out = [], None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn(*args)
        ts.append(time.perf_counter() - t0)
    return float(np.median(ts)), out
