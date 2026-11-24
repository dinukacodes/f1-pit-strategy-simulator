"""
calibrate.py - ground the simulator in real Singapore Grand Prix data.

Inputs (small CSV files in data/, see data/README.md):
  singapore_laps.csv, singapore_pit_stops.csv, singapore_races.csv   (Jolpica-F1, 2008-2025)
  openf1_stints.csv, openf1_laps.csv, openf1_pit.csv, openf1_race_control.csv   (OpenF1, 2023-2025)

What it estimates:
  * per-lap track status (Green / VSC / SC) inferred from the field's lap times,
    validated against OpenF1 race-control messages;
  * the Markov chain by maximum likelihood (transition counts), a Beta posterior
    for P_GS, the lap-1 SC probability and the phase-type SC duration law;
  * neutralised pace ratios k_VSC, k_SC;
  * the Green net pit-transit loss, the stationary-time distribution (2025,
    80 km/h pit lane) and the bypassed-section time T_bypass from Safety-Car stops;
  * per-compound tyre wear rates from clean stints (2023-2025);
  * held-out validation metrics (wear on 2025 stints, SC durations and onsets on 2018-2025).

Only numpy and the standard library are required.
"""

import csv
import io
import math
import os
import urllib.request

import numpy as np

GREEN, VSC, SC = 0, 1, 2
RAW_URL = "https://raw.githubusercontent.com/dinukacodes/f1-pit-strategy-simulator/main/data/"
SOURCE = ("Jolpica-F1 (Ergast successor) https://github.com/jolpica/jolpica-f1 and OpenF1 https://openf1.org, "
          "Singapore Grand Prix 2008-2025, CC BY-NC-SA 4.0")
NEUTRAL_RATIO = 1.18     # lap slower than 118% of Green pace -> neutralised (lap >= 2)
LAP1_RATIO = 1.25        # a standing start is slow anyway, so lap 1 needs a higher bar
MIN_STINTS = 30         # a compound needs >= 30 clean stints for its own wear estimate
SC_GAP_S = 1.5           # field closed up to < 1.5 s median gap -> Safety Car (bunching)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _find_data_dir():
    here = os.path.dirname(os.path.abspath(globals().get("__file__", "x")))
    for d in ("data", "../data", os.path.join(here, "..", "data")):
        if os.path.exists(os.path.join(d, "singapore_laps.csv")):
            return d
    return None


def read_csv(name, data_dir=None):
    """Read data/<name> as a dict of numpy arrays (numbers converted where possible).

    Falls back to the copy on GitHub when the file is not available locally (Colab)."""
    d = data_dir or _find_data_dir()
    if d is not None and os.path.exists(os.path.join(d, name)):
        text = open(os.path.join(d, name), encoding="utf-8").read()
    else:
        with urllib.request.urlopen(RAW_URL + name, timeout=60) as r:
            text = r.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    out = {}
    for k in rows[0]:
        col = [r[k] for r in rows]
        try:
            out[k] = np.array([float(v) if v != "" else np.nan for v in col])
        except ValueError:
            out[k] = np.array(col)
    return out


def load_all(data_dir=None):
    names = ["singapore_laps", "singapore_pit_stops", "singapore_races", "openf1_stints",
             "openf1_laps", "openf1_pit", "openf1_race_control"]
    return {n: read_csv(n + ".csv", data_dir) for n in names}


# ---------------------------------------------------------------------------
# Track status from lap times
# ---------------------------------------------------------------------------

def _runs(mask):
    """[(start, end)] index runs where mask is True (inclusive)."""
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def race_matrix(laps, year):
    """(n_laps, n_drivers) lap-time matrix [s] for one race, NaN where a car did not run."""
    m = laps["year"] == year
    drivers = sorted(set(laps["driver"][m]))
    n = int(laps["lap"][m].max())
    T = np.full((n, len(drivers)), np.nan)
    col = {d: j for j, d in enumerate(drivers)}
    for l, d, t in zip(laps["lap"][m], laps["driver"][m], laps["time_s"][m]):
        T[int(l) - 1, col[d]] = t
    return T, drivers


def infer_status(laps, year):
    """Infer Green / VSC / SC for every lap of one race.

    A lap is neutralised when the field's median lap time exceeds NEUTRAL_RATIO
    times the race's Green pace. A neutralised period is a Safety Car when the
    field has closed up behind it (median gap among the top ten < SC_GAP_S at
    its end), otherwise a VSC (which keeps the gaps). Returns dict(status,
    ratio, ref_s, runs) with runs = [(first_lap, last_lap, kind, end_gap_s)].
    """
    T, _ = race_matrix(laps, year)
    med = np.nanmedian(T, axis=1)
    ref = np.median(med[1:])
    ratio = med / ref
    neutral = ratio > NEUTRAL_RATIO
    neutral[0] = ratio[0] > LAP1_RATIO
    cum = np.cumsum(np.nan_to_num(T, nan=0.0), axis=0)
    cum[~np.isfinite(T)] = np.nan
    status = np.zeros(len(med), dtype=int)
    runs = []
    for a, b in _runs(neutral):
        row = np.sort(cum[b][np.isfinite(cum[b])])[:10]
        end_gap = float(np.median(np.diff(row))) if len(row) > 2 else np.nan
        if year < 2015:
            kind = SC                                   # the VSC exists from 2015
        elif b == a:
            kind = VSC                                  # an SC takes at least two laps (deploy + in)
        else:
            kind = SC if end_gap < SC_GAP_S else VSC
        status[a:b + 1] = kind
        runs.append((a + 1, b + 1, kind, end_gap))
    return dict(status=status, ratio=ratio, ref_s=float(ref), runs=runs)


def all_status(data):
    years = [int(y) for y in data["singapore_races"]["year"]]
    return {y: infer_status(data["singapore_laps"], y) for y in years}


def race_control_check(data, status):
    """OpenF1 race-control Safety-Car / VSC messages next to the inferred status of that lap."""
    rc = data["openf1_race_control"]
    out = []
    for y, l, msg in zip(rc["year"], rc["lap"], rc["message"]):
        y, l = int(y), int(l)
        if "SAFETY CAR" in msg and "INFRINGEMENT" not in msg and y in status:
            out.append((y, l, msg, int(status[y]["status"][l - 1])))
    return out


# ---------------------------------------------------------------------------
# Markov chain estimation
# ---------------------------------------------------------------------------

def transition_counts(seqs):
    """3x3 lap-to-lap transition counts n_ij over all races."""
    C = np.zeros((3, 3), dtype=int)
    for s in seqs:
        for a, b in zip(s[:-1], s[1:]):
            C[a, b] += 1
    return C


def mle_matrix(C):
    """Maximum-likelihood transition matrix P_ij = n_ij / sum_k n_ik."""
    C = np.asarray(C, float)
    return C / np.maximum(C.sum(1, keepdims=True), 1)


def durations(seqs, state):
    out = []
    for s in seqs:
        for a, b in _runs(np.asarray(s) == state):
            out.append(b - a + 1)
    return np.array(out)


def onset_counts(seqs, state):
    """Green -> state onsets (laps >= 2) and the number of Green origins."""
    n_on, n_g = 0, 0
    for s in seqs:
        for l in range(1, len(s)):
            if s[l - 1] == GREEN:
                n_g += 1
                n_on += int(s[l] == state)
    return n_on, n_g


def beta_ci(k, n, level=0.95, prior=(1.0, 1.0), seed=0):
    """Posterior mean and equal-tailed credible interval for a Bernoulli probability."""
    rng = np.random.default_rng(seed)
    a, b = prior[0] + k, prior[1] + n - k
    d = rng.beta(a, b, 400_000)
    return a / (a + b), float(np.quantile(d, (1 - level) / 2)), float(np.quantile(d, (1 + level) / 2))


def phase_type_fit(D):
    """m = min duration, p_SS = sum(D - m) / sum(D - m + 1) (maximum likelihood)."""
    D = np.asarray(D, float)
    m = int(D.min())
    return m, float((D - m).sum() / (D - m + 1).sum())


def phase_type_cdf(x, m, pss):
    x = np.floor(np.asarray(x, float))
    return np.where(x < m, 0.0, 1.0 - pss ** (x - m + 1))


def ks_discrete(D, m, pss):
    """KS distance between the empirical law of D and the phase-type law."""
    D = np.sort(np.asarray(D, float))
    xs = np.arange(1, D.max() + 2)
    emp = np.array([(D <= x).mean() for x in xs])
    return float(np.max(np.abs(emp - phase_type_cdf(xs, m, pss))))


def ks_pvalue_bootstrap(D, m, pss, n_boot=4000, seed=1):
    """Parametric-bootstrap p-value of the KS distance for a fixed (held-out) law."""
    rng = np.random.default_rng(seed)
    d0 = ks_discrete(D, m, pss)
    sims = m + rng.geometric(1 - pss, size=(n_boot, len(D))) - 1 if pss > 0 else np.full((n_boot, len(D)), m)
    ds = np.array([ks_discrete(s, m, pss) for s in sims])
    return d0, float((ds >= d0 - 1e-12).mean())


def poisson_two_sided_p(k, lam):
    pmf = lambda j: math.exp(-lam + j * math.log(lam) - math.lgamma(j + 1))
    pk = pmf(k)
    return min(1.0, sum(pmf(j) for j in range(0, int(lam * 4 + 30)) if pmf(j) <= pk * (1 + 1e-9)))


# ---------------------------------------------------------------------------
# Neutralised pace and pit loss
# ---------------------------------------------------------------------------

def neutral_ratios(status):
    """Median lap-time ratio on the interior laps of SC and VSC periods (edge laps are partial)."""
    out = {}
    for kind in (SC, VSC):
        r = []
        for y, s in status.items():
            for a, b, k, _ in s["runs"]:
                if k == kind:
                    inner = range(a + 1, b) if b - a >= 2 else range(a, b + 1)
                    r += [s["ratio"][l - 1] for l in inner if l > 1]
        out[kind] = (float(np.median(r)), len(r)) if r else (np.nan, 0)
    return out


def stop_losses(data, status, year):
    """Net pit losses [s] of one race: in-lap + out-lap minus two reference laps.

    Green stops use the driver's median clean Green lap; stops whose in-lap and
    out-lap are both under SC use the field's median on those laps (the SC pace)."""
    T, drivers = race_matrix(data["singapore_laps"], year)
    col = {d: j for j, d in enumerate(drivers)}
    ps = data["singapore_pit_stops"]
    m = ps["year"] == year
    st = status[year]["status"]
    pit_laps = {}
    for d, l in zip(ps["driver"][m], ps["lap"][m]):
        pit_laps.setdefault(d, set()).update({int(l), int(l) + 1})
    med = np.nanmedian(T, axis=1)
    green, under_sc = [], []
    for d, l in zip(ps["driver"][m], ps["lap"][m]):
        l, j = int(l), col.get(d)
        if j is None or l + 1 > T.shape[0] or l < 2:
            continue
        tin, tout = T[l - 1, j], T[l, j]
        if not (np.isfinite(tin) and np.isfinite(tout)):
            continue
        if st[l - 1] == GREEN and st[l] == GREEN:
            clean = [T[k, j] for k in range(1, T.shape[0])
                     if st[k] == GREEN and (k + 1) not in pit_laps.get(d, ()) and np.isfinite(T[k, j])]
            if len(clean) >= 10:
                loss = tin + tout - 2 * np.median(clean)
                if 0 < loss < 60:
                    green.append(loss)
        elif st[l - 1] == SC and st[l] == SC:
            loss = tin + tout - med[l - 1] - med[l]
            if -10 < loss < 60:
                under_sc.append(loss)
    return dict(green=np.array(green), sc=np.array(under_sc))


def fit_shifted_lognormal(x, shift):
    y = np.log(np.asarray(x) - shift)
    return float(y.mean()), float(y.std(ddof=1))


# ---------------------------------------------------------------------------
# Tyre wear from stints
# ---------------------------------------------------------------------------

def clean_stint_laps(data, status, years):
    """Clean Green laps with compound and tyre age: list of (year, stint_key, compound, age, lap, t)."""
    S, L = data["openf1_stints"], data["openf1_laps"]
    lap_t = {(int(y), int(dn), int(l)): (t, int(po)) for y, dn, l, t, po in
             zip(L["year"], L["driver_number"], L["lap"], L["lap_s"], L["pit_out_lap"])}
    rows = []
    for y, dn, sn, c, a, b, age0 in zip(S["year"], S["driver_number"], S["stint"], S["compound"],
                                        S["lap_start"], S["lap_end"], S["tyre_age_at_start"]):
        y, dn, a, b = int(y), int(dn), int(a), int(b)
        if y not in years or c not in ("SOFT", "MEDIUM", "HARD") or y not in status:
            continue
        st = status[y]["status"]
        pts = []
        for l in range(a + 1, b):                       # drop the out-lap (a) and the in-lap (b)
            t, po = lap_t.get((y, dn, l), (np.nan, 1))
            if l >= 3 and np.isfinite(t) and not po and l <= len(st) and st[l - 1] == GREEN \
                    and st[l - 2] == GREEN:             # also drop the restart lap after a neutralisation
                pts.append((l, (age0 if age0 == age0 else 0) + (l - a), t))
        if len(pts) >= 6:
            ts = np.array([q[2] for q in pts])
            keep = ts < 1.03 * np.median(ts)            # traffic, mistakes, blue flags
            rows += [(y, "%d-%d-%d" % (y, dn, int(sn)), c, age, l, t) for (l, age, t), k in zip(pts, keep) if k]
    return rows


def fit_wear(rows, fuel_slope_s_per_lap):
    """Per-compound wear slope [s per lap of tyre age] with stint fixed effects.

    Lap times are corrected for fuel burn (t + fuel_slope * (lap - 1)), demeaned
    within each stint, and the slope is pooled least squares on the demeaned data.
    Returns {compound: (slope, standard error, n_laps, n_stints)}."""
    out = {}
    for c in ("SOFT", "MEDIUM", "HARD"):
        r = [x for x in rows if x[2] == c]
        keys = sorted(set(x[1] for x in r))
        if len(keys) < 2:
            continue
        xs, ys = [], []
        for k in keys:
            rr = [x for x in r if x[1] == k]
            a = np.array([x[3] for x in rr], float)
            t = np.array([x[5] + fuel_slope_s_per_lap * (x[4] - 1) for x in rr])
            xs.append(a - a.mean())
            ys.append(t - t.mean())
        x, y = np.concatenate(xs), np.concatenate(ys)
        b = float((x * y).sum() / (x * x).sum())
        resid = y - b * x
        dof = max(len(x) - len(keys) - 1, 1)
        out[c] = (b, float(math.sqrt((resid ** 2).sum() / dof / (x * x).sum())), len(x), len(keys))
    return out


def stint_prediction_rmse(rows, slopes, fuel_slope_s_per_lap, n_anchor=3):
    """Held-out test: anchor each stint on its first n_anchor clean laps and predict the rest.

    Returns (rmse_model, rmse_no_wear, n_predicted_laps)."""
    e_m, e_f = [], []
    for k in sorted(set(x[1] for x in rows)):
        rr = sorted([x for x in rows if x[1] == k], key=lambda x: x[4])
        if len(rr) <= n_anchor + 2 or rr[0][2] not in slopes:
            continue
        a = np.array([x[3] for x in rr], float)
        t = np.array([x[5] + fuel_slope_s_per_lap * (x[4] - 1) for x in rr])
        b = slopes[rr[0][2]]
        c0 = np.mean(t[:n_anchor] - b * a[:n_anchor])
        e_m += list(t[n_anchor:] - (c0 + b * a[n_anchor:]))
        e_f += list(t[n_anchor:] - np.mean(t[:n_anchor]))
    e_m, e_f = np.array(e_m), np.array(e_f)
    return float(np.sqrt(np.mean(e_m ** 2))), float(np.sqrt(np.mean(e_f ** 2))), len(e_m)


# ---------------------------------------------------------------------------
# Everything together
# ---------------------------------------------------------------------------

def calibrate(data=None, p=None):
    """Run the full calibration.

    Returns a dict with the inferred status, the Markov-chain estimates, the pit
    and tyre fits, 'params' (changes to apply with f1sim.with_params) and
    'validation' (held-out metrics)."""
    import f1sim as F
    data = data or load_all()
    p = p or F.default_params()
    status = all_status(data)
    years = sorted(status)
    seqs = [status[y]["status"] for y in years]
    C = transition_counts(seqs)
    P = mle_matrix(C)
    lap1_sc = sum(int(s[0] == SC) for s in seqs)
    n_gs, n_g = onset_counts(seqs, SC)
    vsc_seqs = [status[y]["status"] for y in years if y >= 2015]
    n_gv, n_gv_g = onset_counts(vsc_seqs, VSC)
    D_sc = durations(seqs, SC)
    D_v = durations(vsc_seqs, VSC)
    m_sc, pss = phase_type_fit(D_sc)
    ratios = neutral_ratios(status)
    k_sc = ratios[SC][0]

    # crew time and Green pit loss (2025, 80 km/h pit lane)
    of = data["openf1_pit"]
    stop25 = of["stop_s"][(of["year"] == 2025) & np.isfinite(of["stop_s"])]
    shift = float(np.floor((stop25.min() - 0.1) * 10) / 10)
    mu, sg = fit_shifted_lognormal(stop25, shift)
    L25 = stop_losses(data, status, 2025)
    dT_G = float(np.median(L25["green"]) - np.median(stop25))
    # SC discount on the pit loss, measured: in a race with both Green and SC stops the
    # crew time cancels in median(Green loss) - median(SC loss) = alpha_SC * dT_G(year),
    # with dT_G(year) = median(Green loss) - E[C]. Geometry (R10) predicts
    # alpha_SC = (k_SC - 1) T_bypass / dT_G; the implied T_bypass is reported too.
    mean_crew = shift + math.exp(mu + sg ** 2 / 2)
    tb = []
    for y in years:
        if y >= 2011:
            Ly = stop_losses(data, status, y)
            if len(Ly["sc"]) >= 3 and len(Ly["green"]) >= 3:
                g, s_ = np.median(Ly["green"]), np.median(Ly["sc"])
                tb.append(dict(year=y, n_sc=len(Ly["sc"]), n_green=len(Ly["green"]), green_s=float(g), sc_s=float(s_),
                               alpha_sc=float((g - s_) / (g - mean_crew))))
    alpha_sc = float(np.median([x["alpha_sc"] for x in tb])) if tb else p["alpha_sc"]
    t_bypass = alpha_sc * dT_G / (k_sc - 1)

    # tyre wear: fit on 2023-2024, test on 2025; the final fit uses all three seasons
    fuel_slope = p["gamma_s_per_kg"] * p["burn_kg_per_lap"]
    tr = clean_stint_laps(data, status, {2023, 2024})
    te = clean_stint_laps(data, status, {2025})
    allr = clean_stint_laps(data, status, {2023, 2024, 2025})
    w_tr, w_all = fit_wear(tr, fuel_slope), fit_wear(allr, fuel_slope)
    rmse_m, rmse_f, n_te = stint_prediction_rmse(te, {c: v[0] for c, v in w_tr.items()}, fuel_slope)
    # the model's average wear growth per lap is ~ k_c * (1 + beta * m_mid) (eta is small)
    m_mid = p["m0_kg"] - p["burn_kg_per_lap"] * (p["n_laps"] / 2)
    k_fit = dict(p["k_s_per_lap"])
    for c, v in w_all.items():
        if v[3] >= MIN_STINTS:
            k_fit[c] = max(v[0], 0.005) / (1 + p["beta_per_kg"] * m_mid)
    for c in ("SOFT", "MEDIUM", "HARD"):            # thinly observed compounds keep the assumed ratio to MEDIUM
        if c not in w_all or w_all[c][3] < MIN_STINTS:
            k_fit[c] = k_fit["MEDIUM"] * p["k_s_per_lap"][c] / p["k_s_per_lap"]["MEDIUM"]

    # held-out Markov-chain tests: fit on 2008-2017, test on 2018-2025
    old = [status[y]["status"] for y in years if y <= 2017]
    new = [status[y]["status"] for y in years if y >= 2018]
    m_old, pss_old = phase_type_fit(durations(old, SC))
    D_new = durations(new, SC)
    ks_d, ks_p = ks_pvalue_bootstrap(D_new, m_old, pss_old)
    k_old, n_old = onset_counts(old, SC)
    k_new, n_new = onset_counts(new, SC)
    lam = k_old / n_old * n_new

    params = dict(
        p_gs=n_gs / n_g, p_gv=n_gv / n_gv_g if n_gv else p["p_gv"],
        p_vv=float(P[VSC, VSC]) if C[VSC].sum() else p["p_vv"],
        p_lap1_sc=lap1_sc / len(seqs), sc_min_laps=m_sc, p_ss=pss,
        k_sc=k_sc, k_vsc=ratios[VSC][0] if ratios[VSC][1] else p["k_vsc"],
        crew_shift_s=shift, crew_mu=mu, crew_sigma=sg,
        t_bypass_s=t_bypass, t_pit_s=dT_G + t_bypass, k_s_per_lap=k_fit,
    )
    vsc_geom = (params["k_vsc"] - 1) * t_bypass / dT_G
    params.update(alpha_sc=alpha_sc, alpha_vsc=min(vsc_geom, 0.95), dT_green_s=dT_G)
    return dict(
        status=status, years=years, transition_counts=C, P=P, n_races=len(seqs), source=SOURCE,
        lap1_sc=lap1_sc, onsets_sc=(n_gs, n_g), onsets_vsc=(n_gv, n_gv_g), p_gs_posterior=beta_ci(n_gs, n_g),
        sc_durations=D_sc, vsc_durations=D_v, sc_fit=(m_sc, pss), ratios=ratios,
        crew=dict(stops=stop25, shift=shift, mu=mu, sigma=sg, mean=shift + math.exp(mu + sg ** 2 / 2)),
        pit2025=L25, dT_G=dT_G, sc_stop_years=tb, alpha_sc=alpha_sc, t_bypass=t_bypass, wear_train=w_tr, wear_all=w_all, wear_rows=allr,
        race_control=race_control_check(data, status), params=params,
        validation=dict(
            heldout_wear_rmse_s=rmse_m, heldout_no_wear_rmse_s=rmse_f, heldout_wear_laps=n_te,
            heldout_sc_duration_ks=ks_d, heldout_sc_duration_ks_p=ks_p,
            heldout_sc_onsets_observed=k_new, heldout_sc_onsets_expected=lam,
            heldout_sc_onsets_poisson_p=poisson_two_sided_p(k_new, lam),
            train_sc_fit=(m_old, pss_old), test_sc_durations=D_new,
        ),
    )
