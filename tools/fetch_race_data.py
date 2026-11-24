"""
fetch_race_data.py - download Singapore Grand Prix lap and pit-stop data from the
Jolpica F1 API (the open successor of the Ergast motor-racing API) into data/.

Standard library only. Needs internet access; respects the API's rate limit
(<= 4 requests/s, <= 500/hour) by sleeping between requests.

Writes:
  data/singapore_races.csv      year, round, date, laps (race distance)
  data/singapore_laps.csv       year, lap, driver, position, time_s   (one row per car per lap)
  data/singapore_pit_stops.csv  year, driver, stop, lap, pitlane_s    (pit-lane entry -> exit)
  data/singapore_results.csv    year, driver, grid, position, laps, status

Usage:  python tools/fetch_race_data.py [--years 2008 ... 2025]
Track status (Green / VSC / SC per lap) is not in this API; src/calibrate.py
infers it from the lap times (see THEORY.md, "Real-data calibration").
"""
import argparse
import csv
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://api.jolpi.ca/ergast/f1"
YEARS = [y for y in range(2008, 2026) if y not in (2020, 2021)]   # no race in 2020-21
_last = [0.0]


def get(url, tries=5):
    for k in range(tries):
        wait = 0.35 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pit-strategy-simulator data fetch"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["MRData"]
        except Exception as e:                       # 429 / transient network errors: back off
            print("  retry", k + 1, url, e)
            time.sleep(5 * (k + 1))
    raise RuntimeError("failed: " + url)


def paged(url, key_path, limit=100):
    """Yield all items of a paginated endpoint; key_path walks e.g. RaceTable.Races."""
    offset, total = 0, None
    while total is None or offset < total:
        d = get("%s?limit=%d&offset=%d" % (url, limit, offset))
        total = int(d["total"])
        node = d
        for k in key_path:
            node = node[k]
        yield node
        offset += limit


def t2s(t):
    """'1:42.345' or '42.345' -> seconds."""
    parts = t.split(":")
    s = 0.0
    for p in parts:
        s = s * 60 + float(p)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=YEARS)
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    races, laps, pits, results = [], [], [], []
    for y in a.years:
        rr = get("%s/%d/circuits/marina_bay/races.json" % (BASE, y))["RaceTable"]["Races"]
        if not rr:
            print(y, "no Singapore race")
            continue
        rnd = int(rr[0]["round"])
        res = get("%s/%d/%d/results.json?limit=40" % (BASE, y, rnd))["RaceTable"]["Races"][0]["Results"]
        n_laps = max(int(r["laps"]) for r in res)
        races.append(dict(year=y, round=rnd, date=rr[0]["date"], laps=n_laps))
        for r in res:
            results.append(dict(year=y, driver=r["Driver"]["driverId"], grid=r["grid"],
                                position=r["position"], laps=r["laps"], status=r["status"]))
        nl = 0
        for chunk in paged("%s/%d/%d/laps.json" % (BASE, y, rnd), ["RaceTable", "Races"]):
            for race in chunk:
                for lap in race["Laps"]:
                    for t in lap["Timings"]:
                        laps.append(dict(year=y, lap=int(lap["number"]), driver=t["driverId"],
                                         position=int(t["position"]), time_s=round(t2s(t["time"]), 3)))
                        nl += 1
        npit = 0
        if y >= 2011:                                  # pit-stop timing exists from 2011
            for chunk in paged("%s/%d/%d/pitstops.json" % (BASE, y, rnd), ["RaceTable", "Races"]):
                for race in chunk:
                    for s in race.get("PitStops", []):
                        try:
                            dur = round(t2s(s["duration"]), 3)
                        except (KeyError, ValueError):
                            dur = ""
                        pits.append(dict(year=y, driver=s["driverId"], stop=int(s["stop"]),
                                         lap=int(s["lap"]), pitlane_s=dur))
                        npit += 1
        print(y, "round", rnd, "laps", n_laps, "lap rows", nl, "pit stops", npit)

    def write(name, rows):
        with open(os.path.join(a.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("wrote", name, len(rows), "rows")

    write("singapore_races.csv", races)
    write("singapore_laps.csv", laps)
    write("singapore_pit_stops.csv", pits)
    write("singapore_results.csv", results)


if __name__ == "__main__":
    main()
