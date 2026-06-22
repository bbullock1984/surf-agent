# Surf Agent Project Summary
**Spot:** Remsen Ave & Ocean Ave N, Spring Lake, NJ
**Goal:** A daily-updating RSS feed that reports surf conditions for the next 7 days, so you don't have to manually check forecasts.

---

## 1. The Ideal Conditions (current, final version)

| Variable | IDEAL | INTERESTING | NOT IDEAL |
|---|---|---|---|
| Wave height | 1–2 ft | 0.8–2.4 ft | outside that |
| Swell period | 8–12 sec | 6.0–8 sec or 12–14.4 sec | <6.0 sec or >14.4 sec |
| Wind speed | <10 kt | 10–12 kt | ≥12 kt |
| Wind direction | 225–315° (SW–NW) | 207–333° | outside that |
| Tide | Low to low-mid | — | informational only, not scored |
| Swell direction | ENE or S | — | informational only, no hard cutoff |
| Rip current risk | Low | — | shown but not scored; day 1 is the real NWS call, days 2-7 are estimated |

A day's overall verdict = the **best** classification reached by any single daylight hour (6am–7pm) that day.

### How we got here
- **Wave height (1-2 ft)**: directly from your stated preference.
- **Period floor (originally 8 sec, interesting-floor now 6.0 sec)**: your first "almost perfect" session had a few gutless waves. Wave energy scales with height² × period, so the fix was more period, not more height — going from ~7 sec typical summer windswell to 8 sec added the ~10-15% more energy you wanted. The interesting-tier floor was loosened from 6.4 to 6.0 sec after a real session (6/21/26: 1.8ft @ 6.2 sec) felt fine in person but the original threshold called it NOT IDEAL — real-world feedback overrode the original estimate.
- **Period ceiling (12 sec)**: past ~12-13 sec, swell starts overpowering a small beach break regardless of height — bigger, less predictable sets, and (per NWS's own logic) higher rip risk.
- **Wind (<10kt, SW-NW)**: SW-NW is the established offshore direction for this stretch of coast.
- **Tide/swell direction**: identified as locally preferred but never turned into hard cutoffs — not currently scored in the live feed.
- **Rip risk**: sourced from NWS Mount Holly's Surf Zone Forecast, zone NJZ014 (confirmed correct zone since it uses Belmar — same station as our tide data — as its reference point).

---

## 2. Backtest Results (before the rip-risk/period-floor refinements)

Using a year of real NOAA buoy 44065 data (NY Harbor Entrance, ~22mi from Spring Lake):

- **IDEAL: ~37 days/year** (~10%, roughly 1 in 9-10 days)
- **INTERESTING: ~48 days/year** (~13%)
- **Combined: ~85 days/year** (~23%, roughly 1 in 4)

Notable: June over-performed expectations (close to half its days landed IDEAL/INTERESTING), while October, December, and March underperformed (1-4 good days out of ~30).

*Note: the backtest used the original 6.4 sec period floor — the 6.0 sec update happened after, so a literal re-run would shift these numbers slightly upward.*

---

## 3. How the Live Agent Works

**Architecture:** GitHub repo → GitHub Actions (runs daily) → writes `docs/feed.xml` → GitHub Pages serves it → Reeder subscribes to the URL.

**Data sources (all free, no API keys):**
- **Open-Meteo Marine API** — wave height, period, direction, sea surface temperature (7-day hourly forecast)
- **Open-Meteo Forecast API** — wind speed/direction (7-day hourly forecast)
- **NOAA CO-OPS Tides API** — official low/high tide predictions, station 8532337 (Belmar, NJ)
- **NWS api.weather.gov** — official Surf Zone Forecast text bulletin, zone NJZ014, for the nearest day's rip-current risk only (NWS doesn't publish a multi-day version)

**Feed behavior:**
- Runs once daily via cron (~11:00 UTC / ~7am Eastern)
- Publishes **one single RSS item per day** (not one per forecast day) — the item's body lists all 7 upcoming days
- Each day shows: day of week + date, IDEAL/INTERESTING/NOT IDEAL badge, best hour's stats (wave height, period, wind speed + compass direction, water temp), low tide time(s), and rip-current risk (labeled "(NWS)" for day 1, "(estimated)" for days 2-7)
- NOT IDEAL days include a plain-language reason (e.g., "period too long, wind too strong")

**Repo files:**
- `fetch_and_build_feed.py` — the main script
- `.github/workflows/daily-surf-feed.yml` — the daily automation
- `test_logic.py` — a local test harness using realistic mock data (doesn't hit the real APIs, just verifies the logic)
- `docs/feed.xml` — the generated feed (auto-updated daily, this is what Reeder subscribes to)

---

## 4. Known Limitations

- **Coordinates are approximate** (Spring Lake oceanfront, ~40.1500, -74.0010) — fine in practice since the forecast model grid is ~5-25km resolution, far coarser than street-level.
- **Buoy used for backtesting was offshore and north** of Spring Lake (NY Harbor area) — a reasonable proxy, not a perfect match for what breaks at Remsen Ave specifically.
- **Tide stage (low/low-mid) and swell direction are informational only** — not yet built into the scoring logic, only the daily summary text.
- **Rip-current risk beyond day 1 is an estimate**, not an official NWS forecast — always check the live NWS call yourself before an actual session.
- **The feed file only ever holds the latest single item** — no growing in-file history, though Reeder retains its own read history regardless.

---

## 5. Troubleshooting Notes (things that already came up once)

- **GitHub web editor mix-ups**: when copy-pasting between the `.py` and `.yml` files, it's easy to accidentally paste one's content into the other. If a workflow run fails with a Python `SyntaxError` pointing at YAML-looking text (e.g. `name: Daily Surf Forecast Feed`), that's the tell.
- **"Re-run jobs" vs "Run workflow"**: re-running an old run reuses its original commit, which can cause a `git push` rejection if you've since edited files. Always use **Run workflow** (from the workflow's overview page, not an individual run's page) for a fresh run after making edits.
- **"Node.js 20 is deprecated" warning**: harmless, unrelated to this project, safe to ignore.
- The workflow includes a `git pull --rebase --autostash` step before pushing specifically to make the above conflict self-resolve in normal daily runs.

---

## 6. Possible Future Enhancements (not yet built)

- Score tide stage and swell direction instead of just displaying them
- Extend rip-risk to use NWS's experimental 6-day probabilistic Surf Forecast Matrix instead of a simple estimate (exists, but not in an easily scriptable format yet)
- Retain a rolling history of past days' verdicts inside the feed file itself
- Tighten Remsen Ave's exact coordinates if a more precise source is ever found
