"""
fetch_fastf1_data.py - build the small derived Singapore data set in data/ from FastF1.

Needs internet access and `pip install fastf1 pandas`. The raw FastF1 cache is
written to .fastf1_cache/ (git-ignored); only small derived tables are written
to data/:

  singapore_track_status.csv   year, lap, status (0 Green / 1 VSC / 2 SC), codes
  singapore_pit_stops.csv      one row per pit stop with in/out-lap times and pit-lane time
  singapore_stints.csv         one row per stint: compound, start lap, clean-lap fit
  singapore_deg_curves.csv     mean clean-lap time by (year, compound, tyre age)
  singapore_neutralised.csv    SC / VSC lap-time ratios per race

Usage:  python tools/fetch_fastf1_data.py [--years 2018 2019 2022 2023 2024 2025]

FastF1 TrackStatus codes: '1' clear, '2' yellow, '4' Safety Car, '5' red flag,
'6' VSC deployed, '7' VSC ending. A lap counts as SC if any car's code for
that lap contains '4', as VSC if it contains '6' or '7' (SC wins over VSC);
the per-lap status is the most common one across cars.
"""
import argparse
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_YEARS = (2018, 2019, 2022, 2023, 2024, 2025)


def lap_status_from_code(code):
    code = "" if code is None or (isinstance(code, float) and np.isnan(code)) else str(code)
    if "4" in code:
        return 2
    if "6" in code or "7" in code:
        return 1
    return 0


def secs(x):
    return x.dt.total_seconds() if hasattr(x, "dt") else x


def track_status(laps, year):
    df = laps[["LapNumber", "TrackStatus"]].dropna(subset=["LapNumber"]).copy()
    df["s"] = df["TrackStatus"].map(lap_status_from_code)
    rows = []
    for lap, g in df.groupby("LapNumber"):
        s = int(np.bincount(g["s"].astype(int), minlength=3).argmax())
        codes = "".join(sorted(set("".join(str(c) for c in g["TrackStatus"].dropna()))))
        red = "5" in codes
        rows.append(dict(year=year, lap=int(lap), status=s, codes=codes, red_flag=int(red)))
    return pd.DataFrame(rows)


def per_driver(laps):
    for drv, d in laps.groupby("Driver"):
        d = d.sort_values("LapNumber").reset_index(drop=True)
        d["t"] = secs(d["LapTime"])
        d["st"] = d["TrackStatus"].map(lap_status_from_code)
        d["pin"] = d["PitInTime"].notna()
        d["pout"] = d["PitOutTime"].notna() & (d["LapNumber"] > 1)
        yield drv, d


def clean_mask(d):
    """Green laps that are not in/out laps, not lap 1, with a valid time inside 107% of the driver's median."""
    m = (d["st"] == 0) & ~d["pin"] & ~d["pout"] & (d["LapNumber"] > 1) & d["t"].notna()
    if "Deleted" in d:
        m &= ~d["Deleted"].fillna(False).astype(bool)
    if m.sum():
        med = d.loc[m, "t"].median()
        m &= d["t"] < 1.07 * med
    return m


def pit_stops(laps, year):
    rows = []
    for drv, d in per_driver(laps):
        m = clean_mask(d)
        if m.sum() < 5:
            continue
        ref = float(d.loc[m, "t"].median())
        for i in np.nonzero(d["pin"].to_numpy())[0]:
            if i + 1 >= len(d):
                continue                                   # retired in the pit lane / last lap
            a, b = d.iloc[i], d.iloc[i + 1]
            pit_in, pit_out = a["PitInTime"], b["PitOutTime"]
            lane = (pit_out - pit_in).total_seconds() if pd.notna(pit_in) and pd.notna(pit_out) else np.nan
            rows.append(dict(
                year=year, driver=drv, team=a.get("Team", ""), lap=int(a["LapNumber"]),
                compound_before=a.get("Compound", ""), compound_after=b.get("Compound", ""),
                tyre_age_before=a.get("TyreLife", np.nan),
                status_in=int(a["st"]), status_out=int(b["st"]),
                inlap_s=a["t"], outlap_s=b["t"], ref_lap_s=ref,
                net_loss_s=(a["t"] + b["t"] - 2 * ref) if pd.notna(a["t"]) and pd.notna(b["t"]) else np.nan,
                pitlane_s=lane))
    return pd.DataFrame(rows)


def stints_and_curves(laps, year):
    stints, pts = [], []
    for drv, d in per_driver(laps):
        m = clean_mask(d)
        for st, g in d[m].groupby("Stint"):
            comp = str(g["Compound"].iloc[0])
            if comp not in ("SOFT", "MEDIUM", "HARD"):
                continue
            all_laps = d[d["Stint"] == st]
            start, end = int(all_laps["LapNumber"].min()), int(all_laps["LapNumber"].max())
            life0 = float(all_laps["TyreLife"].min()) if all_laps["TyreLife"].notna().any() else np.nan
            row = dict(year=year, driver=drv, stint=int(st), compound=comp, start_lap=start, end_lap=end,
                       tyre_life_at_start=life0, n_clean=len(g), slope_s_per_lap=np.nan,
                       intercept_s=np.nan, median_s=float(g["t"].median()))
            if len(g) >= 6:
                x = g["LapNumber"].to_numpy(float) - start
                y = g["t"].to_numpy(float)
                b1, b0 = np.polyfit(x, y, 1)
                row.update(slope_s_per_lap=b1, intercept_s=b0)
            stints.append(row)
            for _, r in g.iterrows():
                pts.append(dict(year=year, compound=comp, tyre_life=r["TyreLife"], lap=int(r["LapNumber"]), t=r["t"]))
    curves = pd.DataFrame(pts)
    if len(curves):
        curves = (curves.dropna(subset=["tyre_life"]).groupby(["year", "compound", "tyre_life"])
                  .agg(n=("t", "size"), mean_lap_s=("t", "mean"), sd_lap_s=("t", "std"), mean_race_lap=("lap", "mean"))
                  .reset_index())
    return pd.DataFrame(stints), curves


def neutralised_ratios(laps, year):
    df = laps.copy()
    df["t"] = secs(df["LapTime"])
    codes = df["TrackStatus"].astype(str)
    green = df[(codes == "1") & df["PitInTime"].isna() & df["PitOutTime"].isna() & (df["LapNumber"] > 1)]["t"].dropna()
    ref = float(green.median()) if len(green) else np.nan
    out = dict(year=year, ref_green_s=ref)
    for name, code in (("sc", "4"), ("vsc", "6")):
        x = df[(codes == code) & df["PitInTime"].isna() & df["PitOutTime"].isna()]["t"].dropna()
        out["n_" + name + "_laps"] = int(len(x))
        out["median_" + name + "_s"] = float(x.median()) if len(x) else np.nan
        out["k_" + name] = float(x.median() / ref) if len(x) and ref == ref else np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=list(DEFAULT_YEARS))
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    args = ap.parse_args()
    import fastf1
    cache = os.path.join(ROOT, ".fastf1_cache")
    os.makedirs(cache, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    fastf1.Cache.enable_cache(cache)
    status, pits, stints, curves, ratios = [], [], [], [], []
    for y in args.years:
        ses = fastf1.get_session(y, "Singapore", "R")
        ses.load(telemetry=False, weather=False, messages=False)
        laps = ses.laps
        status.append(track_status(laps, y))
        pits.append(pit_stops(laps, y))
        s, c = stints_and_curves(laps, y)
        stints.append(s)
        curves.append(c)
        ratios.append(neutralised_ratios(laps, y))
        seq = "".join("GVS"[v] for v in status[-1]["status"])
        print(y, "laps", len(status[-1]), "stops", len(pits[-1]), "stints", len(s), "|", seq)
    pd.concat(status).to_csv(os.path.join(args.out, "singapore_track_status.csv"), index=False)
    pd.concat(pits).round(3).to_csv(os.path.join(args.out, "singapore_pit_stops.csv"), index=False)
    pd.concat(stints).round(4).to_csv(os.path.join(args.out, "singapore_stints.csv"), index=False)
    pd.concat(curves).round(3).to_csv(os.path.join(args.out, "singapore_deg_curves.csv"), index=False)
    pd.DataFrame(ratios).round(4).to_csv(os.path.join(args.out, "singapore_neutralised.csv"), index=False)
    print("wrote", sorted(f for f in os.listdir(args.out) if f.endswith(".csv")))


if __name__ == "__main__":
    main()
