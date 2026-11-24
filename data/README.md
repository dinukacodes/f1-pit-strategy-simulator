# Data: sources, contents and licence

All files are small CSV extracts for the **Singapore Grand Prix** (Marina Bay), used by `src/calibrate.py` and notebook §6.7–6.8. The notebook reads them locally, or from this repository on GitHub when it runs in Colab, so no API calls are needed to run it.

## Sources and licence

| Source | What | Licence |
|---|---|---|
| **Jolpica-F1**, the open-source successor of the Ergast motor-racing API, <https://github.com/jolpica/jolpica-f1> (API: `https://api.jolpi.ca/ergast/f1/`) | lap times, pit stops, results, 2008–2025 | **CC BY-NC-SA 4.0** ([TERMS.md](https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md): *"The data is licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)."*) |
| **OpenF1**, <https://openf1.org> (API: `https://api.openf1.org/v1/`) | tyre stints and compounds, lap times, pit-lane and stationary times, race-control messages, 2023–2025 | **CC BY-NC-SA 4.0** (stated on openf1.org) |

The files in this folder are redistributed in reduced form, unchanged in substance, under the same licence (**CC BY-NC-SA 4.0**): attribution as above, **non-commercial use only**, and share-alike. The MIT licence of the code in this repository does **not** apply to the data. Formula 1 timing data originates from the official live-timing service. This project is independent and has no affiliation with Formula 1, the FIA, any team, Jolpica or OpenF1.

Accessed 24 November 2026 with `tools/fetch_race_data.py` (Jolpica) and `tools/fetch_openf1_data.py` (OpenF1). Both scripts use only the Python standard library and respect the APIs' rate limits.

## Files

| File | Rows | Columns | Notes |
|---|---:|---|---|
| `singapore_races.csv` | 16 | `year, round, date, laps` | 2008–2019 and 2022–2025 (no race in 2020–21). 2012, 2014, 2017 and 2022 were shortened by the two-hour rule. |
| `singapore_laps.csv` | 18,151 | `year, lap, driver, position, time_s` | One row per car per lap. Used to infer Green / VSC / SC per lap and to measure pit losses and neutralised pace. |
| `singapore_pit_stops.csv` | 570 | `year, driver, stop, lap, pitlane_s` | `lap` is the in-lap. `pitlane_s` is the pit-lane time from entry to exit, including the stop. Available from 2011. |
| `singapore_results.csv` | 338 | `year, driver, grid, position, laps, status` | Classification and retirements. |
| `openf1_stints.csv` | 130 | `year, driver_number, stint, compound, lap_start, lap_end, tyre_age_at_start` | Compound per stint (Jolpica has no compounds). |
| `openf1_laps.csv` | 3,499 | `year, driver_number, lap, lap_s, pit_out_lap` | Lap times for the tyre-wear fit. |
| `openf1_pit.csv` | 71 | `year, driver_number, lap, lane_s, stop_s` | `stop_s` is the stationary time (2025 only), used for the crew-time distribution. |
| `openf1_race_control.csv` | 6 | `year, lap, category, flag, message` | Safety Car and VSC messages, used to validate the inferred track status. 2024 and 2025 had none. |

## How the data are used

See [THEORY.md §3.5](../THEORY.md#35-real-data-calibration) and notebook §6.7. In short:

* **Track status** is inferred from the field's median lap time. A Safety Car is told apart from a VSC by whether the field closes up behind it. The result matches the 2023 race-control messages exactly.
* **Markov chain:** maximum-likelihood transition matrix from the transition counts, a Beta posterior for $P_{GS}$, the lap-1 SC probability and the phase-type SC duration law.
* **Pit lane:** the 2025 Green pit loss and stationary times (80 km/h limit), and the SC pit-loss discount measured in races with both Green and SC stops.
* **Tyres:** per-compound wear rates from clean 2023–2025 stints, with stint fixed effects.
* **Held-out tests:** wear rates fitted on 2023–24 are tested on 2025, and the SC duration law and onset rate fitted on 2008–17 are tested on 2018–25.
