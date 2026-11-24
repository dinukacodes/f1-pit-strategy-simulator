"""
calibrate.py - estimate simulator inputs from FastF1 Singapore race data.

Optional: needs `pip install fastf1 pandas` and internet access to the F1
live-timing archive. Running build_calibration_csv() once writes small CSV
files to data/ so the notebook never has to download anything.

FastF1 TrackStatus codes (per lap, a string of codes that occurred on that
lap): '1' track clear, '2' yellow, '4' Safety Car, '5' red flag,
'6' VSC deployed, '7' VSC ending.
"""

import numpy as np

SINGAPORE_YEARS = (2018, 2019, 2022, 2023, 2024, 2025)   # FastF1 timing exists from 2018


def lap_status_from_code(code):
    """Map a FastF1 TrackStatus string to 0 Green / 1 VSC / 2 SC (SC wins over VSC)."""
    code = "" if code is None else str(code)
    if "4" in code:
        return 2
    if "6" in code or "7" in code:
        return 1
    return 0


def race_status_sequence(laps):
    """Lap-by-lap status of one race from a FastF1 laps DataFrame.

    Uses the most common status across drivers for each lap number, so one
    driver's odd lap does not create a fake transition.
    """
    df = laps[["LapNumber", "TrackStatus"]].dropna(subset=["LapNumber"]).copy()
    df["s"] = df["TrackStatus"].map(lap_status_from_code)
    seq = df.groupby("LapNumber")["s"].agg(lambda x: int(np.bincount(x.astype(int), minlength=3).argmax()))
    return seq.sort_index().to_numpy()


def transition_counts(sequences):
    """3x3 matrix of observed lap-to-lap transitions across races (lap 1 excluded as origin)."""
    C = np.zeros((3, 3), dtype=int)
    for seq in sequences:
        for a, b in zip(seq[:-1], seq[1:]):
            C[a, b] += 1
    return C


def run_lengths(seq, state):
    """Lengths [laps] of consecutive runs of `state` in a status sequence."""
    out, n = [], 0
    for s in list(seq) + [-1]:
        if s == state:
            n += 1
        elif n:
            out.append(n)
            n = 0
    return out


def net_pit_loss(laps):
    """Per-stop net pit loss [s] = (in-lap + out-lap) - 2 * median clean lap of that driver.

    Only stops whose in-lap and out-lap were both Green are kept. Returns a
    numpy array (includes the stationary crew time).
    """
    out = []
    for drv, d in laps.groupby("Driver"):
        d = d.sort_values("LapNumber")
        t = d["LapTime"].dt.total_seconds().to_numpy()
        st = d["TrackStatus"].map(lap_status_from_code).to_numpy()
        pin = d["PitInTime"].notna().to_numpy()
        clean = (~pin) & (st == 0) & np.isfinite(t)
        clean &= ~np.r_[False, pin[:-1]]                  # drop out-laps
        if clean.sum() < 5:
            continue
        ref = np.median(t[clean])
        for i in np.nonzero(pin)[0]:
            if i + 1 < len(t) and st[i] == 0 and st[i + 1] == 0 and np.isfinite(t[i]) and np.isfinite(t[i + 1]):
                out.append(t[i] + t[i + 1] - 2 * ref)
    return np.array(out)


def build_calibration_csv(out_dir="data", years=SINGAPORE_YEARS):
    """Download Singapore races with FastF1 and write status / pit-loss CSVs to out_dir."""
    import os
    import fastf1
    import pandas as pd
    os.makedirs(out_dir, exist_ok=True)
    rows, pits = [], []
    for y in years:
        ses = fastf1.get_session(y, "Singapore", "R")
        ses.load(telemetry=False, weather=False, messages=False)
        seq = race_status_sequence(ses.laps)
        rows += [dict(year=y, lap=i + 1, status=int(s)) for i, s in enumerate(seq)]
        pits += [dict(year=y, net_pit_loss_s=float(v)) for v in net_pit_loss(ses.laps)]
    pd.DataFrame(rows).to_csv(os.path.join(out_dir, "singapore_track_status.csv"), index=False)
    pd.DataFrame(pits).to_csv(os.path.join(out_dir, "singapore_pit_loss.csv"), index=False)


def summarise_status_csv(path):
    """Transition counts, MLE matrix, SC run lengths and race count from the cached CSV."""
    import pandas as pd
    df = pd.read_csv(path)
    seqs = [g.sort_values("lap")["status"].to_numpy() for _, g in df.groupby("year")]
    C = transition_counts(seqs)
    P = C / np.maximum(C.sum(1, keepdims=True), 1)
    sc_runs = [r for s in seqs for r in run_lengths(s, 2)]
    lap1_sc = sum(int(s[0] == 2) for s in seqs)
    return dict(n_races=len(seqs), transition_counts=C, P=P, sc_durations=sc_runs, lap1_sc=lap1_sc)
