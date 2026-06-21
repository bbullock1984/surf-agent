"""
Daily surf forecast -> RSS feed
--------------------------------
Remsen Ave & Ocean Ave N, Spring Lake, NJ

Pulls a 7-day wave/wind forecast (Open-Meteo, free, no key) and tide
predictions (NOAA CO-OPS, free, no key) and writes an RSS 2.0 feed with
one item per day: classification (IDEAL / INTERESTING / NOT IDEAL),
the best hour's stats that day, and that day's low tide time(s).

Classification thresholds match the backtest script exactly:
    Wave height:    1-2 ft   | 0.8-2.4 ft        | outside that
    Swell period:   8-12 sec | 6.4-8 or 12-14.4  | outside that
    Wind speed:     <10 kt   | <12 kt            | >=12 kt
    Wind direction: 225-315 deg (SW-NW) | 207-333 deg | outside that

Rip-current risk and exact tide *stage* (low/low-mid) are NOT part of
the classification -- this only adds low-tide *timing* as reference
info, per the user's request. Rip-risk integration is a separate,
later step (live NWS bulletin, no historical archive, more fragile
text parsing).

Run manually:
    pip3 install requests
    python3 fetch_and_build_feed.py

In production this is run daily by the GitHub Actions workflow in
.github/workflows/daily-surf-feed.yml, which commits docs/feed.xml so
GitHub Pages serves it at a stable URL for Reeder (or any RSS reader).
"""

import datetime
import os
import xml.sax.saxutils as saxutils

import requests

# ---- Location & station ----
# Approximate Spring Lake, NJ oceanfront. Wave/wind model grid resolution
# (~5-25 km) means street-level precision wouldn't change the forecast --
# adjust only if you want a meaningfully different stretch of coast.
LAT, LON = 40.1500, -74.0010
TIDE_STATION = "8532337"  # Belmar, NJ -- same station NWS uses for this coast
TIMEZONE = "America/New_York"
FORECAST_DAYS = 7

OUTPUT_PATH = "docs/feed.xml"
FEED_TITLE = "Spring Lake Surf Conditions \u2014 Remsen Ave"
FEED_LINK = "https://example.com"  # replace with your GitHub Pages URL once known
FEED_DESC = "Daily 7-day surf forecast for Remsen Ave & Ocean Ave N, Spring Lake, NJ"

# ---- Classification thresholds (identical to the backtest script) ----
IDEAL_HEIGHT_FT = (1.0, 2.0)
INTERESTING_HEIGHT_FT = (0.8, 2.4)
IDEAL_PERIOD_SEC = (8.0, 12.0)
INTERESTING_PERIOD_SEC = (6.4, 14.4)
IDEAL_WIND_MAX_KT = 10.0
INTERESTING_WIND_MAX_KT = 12.0
IDEAL_WDIR_DEG = (225, 315)
INTERESTING_WDIR_DEG = (207, 333)

DAYLIGHT_HOURS = range(6, 19)
RANK = {"IDEAL": 0, "INTERESTING": 1, "NOT IDEAL": 2}
BADGE = {"IDEAL": "\U0001F7E2 IDEAL", "INTERESTING": "\U0001F7E1 INTERESTING", "NOT IDEAL": "\U0001F534 NOT IDEAL"}

COMPASS_POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def degrees_to_compass(deg):
    """Convert a wind direction in degrees to a 16-point compass label."""
    idx = int((deg / 22.5) + 0.5) % 16
    return COMPASS_POINTS[idx]

MARINE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"
    "?latitude={lat}&longitude={lon}"
    "&hourly=wave_height,wave_period,wave_direction"
    "&length_unit=imperial&timezone={tz}&forecast_days={days}"
)
WIND_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&hourly=wind_speed_10m,wind_direction_10m"
    "&wind_speed_unit=kn&timezone={tz}&forecast_days={days}"
)
TIDE_URL = (
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    "?begin_date={begin}&end_date={end}&station={station}"
    "&product=predictions&datum=MLLW&time_zone=lst_ldt"
    "&interval=hilo&units=english&application=surf-agent&format=json"
)


def fetch_marine():
    url = MARINE_URL.format(lat=LAT, lon=LON, tz=TIMEZONE, days=FORECAST_DAYS)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_wind():
    url = WIND_URL.format(lat=LAT, lon=LON, tz=TIMEZONE, days=FORECAST_DAYS)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_tides():
    today = datetime.date.today()
    end = today + datetime.timedelta(days=FORECAST_DAYS)
    url = TIDE_URL.format(begin=today.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"), station=TIDE_STATION)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def classify_value(value, ideal_ok, interesting_ok):
    if ideal_ok(value):
        return "IDEAL"
    if interesting_ok(value):
        return "INTERESTING"
    return "NOT IDEAL"


def classify_hour(h):
    """h is a dict with wave_ft, period_s, wind_kt, wind_dir (all floats).
    Returns the overall tier, or None if any field is missing/None."""
    if any(h.get(k) is None for k in ("wave_ft", "period_s", "wind_kt", "wind_dir")):
        return None

    h_class = classify_value(
        h["wave_ft"],
        lambda v: IDEAL_HEIGHT_FT[0] <= v <= IDEAL_HEIGHT_FT[1],
        lambda v: INTERESTING_HEIGHT_FT[0] <= v <= INTERESTING_HEIGHT_FT[1],
    )
    p_class = classify_value(
        h["period_s"],
        lambda v: IDEAL_PERIOD_SEC[0] <= v <= IDEAL_PERIOD_SEC[1],
        lambda v: INTERESTING_PERIOD_SEC[0] <= v <= INTERESTING_PERIOD_SEC[1],
    )
    w_class = classify_value(
        h["wind_kt"],
        lambda v: v < IDEAL_WIND_MAX_KT,
        lambda v: v < INTERESTING_WIND_MAX_KT,
    )
    d_class = classify_value(
        h["wind_dir"],
        lambda v: IDEAL_WDIR_DEG[0] <= v <= IDEAL_WDIR_DEG[1],
        lambda v: INTERESTING_WDIR_DEG[0] <= v <= INTERESTING_WDIR_DEG[1],
    )
    overall_rank = max(RANK[h_class], RANK[p_class], RANK[w_class], RANK[d_class])
    overall = next(k for k, v in RANK.items() if v == overall_rank)
    return overall


def merge_and_classify(marine_json, wind_json, tide_json):
    times = marine_json["hourly"]["time"]
    wvht = marine_json["hourly"]["wave_height"]
    wper = marine_json["hourly"]["wave_period"]

    wind_times = wind_json["hourly"]["time"]
    wspd = wind_json["hourly"]["wind_speed_10m"]
    wdir = wind_json["hourly"]["wind_direction_10m"]
    wind_by_time = {t: (s, d) for t, s, d in zip(wind_times, wspd, wdir)}

    days = {}
    for i, t in enumerate(times):
        if t not in wind_by_time:
            continue
        date_str, time_str = t.split("T")
        hour = int(time_str.split(":")[0])
        if hour not in DAYLIGHT_HOURS:
            continue

        wind_kt, wind_dir = wind_by_time[t]
        h = {"wave_ft": wvht[i], "period_s": wper[i], "wind_kt": wind_kt, "wind_dir": wind_dir}
        overall = classify_hour(h)
        if overall is None:
            continue

        rank = RANK[overall]
        if date_str not in days or rank < days[date_str]["rank"]:
            days[date_str] = {"rank": rank, "class": overall, "hour": hour, **h}

    lows_by_date = {}
    for p in tide_json.get("predictions", []):
        if p.get("type") == "L":
            d, tm = p["t"].split(" ")
            lows_by_date.setdefault(d, []).append(tm[:5])  # HH:MM

    return days, lows_by_date


def build_rss(days, lows_by_date):
    """Builds a feed with ONE item per run (one new post per day), whose
    body lists all 7 upcoming days. The feed file always holds just this
    single latest item -- Reeder (or any reader) already remembers items
    it has seen by guid, so daily history isn't lost from the reader's
    point of view even though old items aren't kept in the file itself."""
    now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    run_date = datetime.date.today().isoformat()
    sorted_dates = sorted(days.keys())

    tally = {"IDEAL": 0, "INTERESTING": 0, "NOT IDEAL": 0}
    text_lines = []
    html_lines = []

    for date_str in sorted_dates:
        info = days[date_str]
        tally[info["class"]] += 1
        lows = lows_by_date.get(date_str, [])
        low_str = ", ".join(lows) if lows else "n/a"
        badge = BADGE[info["class"]]
        wind_compass = degrees_to_compass(info["wind_dir"])

        line = (
            f"{date_str}: {badge} \u2014 best window {info['hour']:02d}:00, "
            f"{info['wave_ft']:.1f} ft @ {info['period_s']:.1f} sec, "
            f"wind {info['wind_kt']:.0f} kt {wind_compass}. Low tide: {low_str}."
        )
        text_lines.append(line)
        html_lines.append(f"<li>{saxutils.escape(line)}</li>")

    if sorted_dates:
        title = f"7-Day Surf Forecast \u2014 {sorted_dates[0]} to {sorted_dates[-1]}"
    else:
        title = f"7-Day Surf Forecast ({run_date})"

    summary = (
        f"{tally['IDEAL']} IDEAL, {tally['INTERESTING']} INTERESTING, "
        f"{tally['NOT IDEAL']} NOT IDEAL over the next {len(sorted_dates)} days."
    )
    description_text = summary + " " + " ".join(text_lines)
    content_html = f"<p>{saxutils.escape(summary)}</p><ul>" + "".join(html_lines) + "</ul>"
    guid = f"run-{run_date}"

    item = (
        "    <item>\n"
        f"      <title>{saxutils.escape(title)}</title>\n"
        f"      <description>{saxutils.escape(description_text)}</description>\n"
        f"      <content:encoded><![CDATA[{content_html}]]></content:encoded>\n"
        f"      <pubDate>{now}</pubDate>\n"
        f"      <guid isPermaLink=\"false\">{saxutils.escape(guid)}</guid>\n"
        "    </item>"
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">\n'
        "  <channel>\n"
        f"    <title>{saxutils.escape(FEED_TITLE)}</title>\n"
        f"    <link>{saxutils.escape(FEED_LINK)}</link>\n"
        f"    <description>{saxutils.escape(FEED_DESC)}</description>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f"{item}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def main():
    marine = fetch_marine()
    wind = fetch_wind()
    tides = fetch_tides()

    days, lows = merge_and_classify(marine, wind, tides)
    xml = build_rss(days, lows)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(xml)

    print(f"Wrote {len(days)} day(s) to {OUTPUT_PATH}")
    for date_str in sorted(days.keys()):
        print(f"  {date_str}: {days[date_str]['class']}")


if __name__ == "__main__":
    main()
