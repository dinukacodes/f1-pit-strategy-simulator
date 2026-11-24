"""
fetch_openf1_data.py - download tyre-stint, lap, pit-stop and race-control data for the
Singapore Grand Prix races 2023-2025 from the OpenF1 API (https://openf1.org) into data/.

OpenF1 serves historical sessions (2023 onwards) free and without authentication.
Standard library only; sleeps between requests to stay well inside the published
limit (3 requests/s, 30 requests/min).

Writes:
  data/openf1_stints.csv        year, driver_number, stint, compound, lap_start, lap_end, tyre_age_at_start
  data/openf1_laps.csv          year, driver_number, lap, lap_s, pit_out_lap
  data/openf1_pit.csv           year, driver_number, lap, lane_s, stop_s   (stop_s = stationary time)
  data/openf1_race_control.csv  year, lap, category, flag, message        (Safety Car / VSC messages)

Usage:  python tools/fetch_openf1_data.py [--years 2023 2024 2025]
"""
import argparse
import csv
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://api.openf1.org/v1"
_last = [0.0]


def get(path, tries=5):
    url = BASE + path
    for k in range(tries):
        wait = 2.2 - (time.time() - _last[0])          # <= 30 requests per minute
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pit-strategy-simulator/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            print("  retry", k + 1, url, e)
        except Exception as e:
            print("  retry", k + 1, url, e)
        time.sleep(5 * (k + 1))
    raise RuntimeError("failed: " + url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*", default=[2023, 2024, 2025])
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    stints, laps, pits, rc = [], [], [], []
    for y in a.years:
        ses = get("/sessions?year=%d&country_name=Singapore&session_name=Race" % y)
        if not ses:
            print(y, "no session")
            continue
        key = ses[0]["session_key"]
        for s in get("/stints?session_key=%d" % key):
            stints.append(dict(year=y, driver_number=s["driver_number"], stint=s["stint_number"],
                               compound=s.get("compound") or "", lap_start=s.get("lap_start"),
                               lap_end=s.get("lap_end"), tyre_age_at_start=s.get("tyre_age_at_start")))
        for l in get("/laps?session_key=%d" % key):
            laps.append(dict(year=y, driver_number=l["driver_number"], lap=l["lap_number"],
                             lap_s=l.get("lap_duration") if l.get("lap_duration") is not None else "",
                             pit_out_lap=int(bool(l.get("is_pit_out_lap")))))
        for p in get("/pit?session_key=%d" % key):
            pits.append(dict(year=y, driver_number=p["driver_number"], lap=p.get("lap_number"),
                             lane_s=p.get("lane_duration", p.get("pit_duration")),
                             stop_s=p.get("stop_duration") if p.get("stop_duration") is not None else ""))
        for m in get("/race_control?session_key=%d" % key):
            msg = (m.get("message") or "").upper()
            if "SAFETY CAR" in msg or m.get("category") == "SafetyCar" or "VSC" in msg:
                rc.append(dict(year=y, lap=m.get("lap_number"), category=m.get("category"),
                               flag=m.get("flag") or "", message=m.get("message")))
        print(y, "session", key, "| stints", sum(r["year"] == y for r in stints),
              "| laps", sum(r["year"] == y for r in laps), "| pit", sum(r["year"] == y for r in pits),
              "| SC/VSC messages", sum(r["year"] == y for r in rc))

    def write(name, rows):
        with open(os.path.join(a.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("wrote", name, len(rows), "rows")

    write("openf1_stints.csv", stints)
    write("openf1_laps.csv", laps)
    write("openf1_pit.csv", pits)
    write("openf1_race_control.csv", rc)


if __name__ == "__main__":
    main()
