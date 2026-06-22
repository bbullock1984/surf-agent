"""
Daily surf forecast -> RSS feed
--------------------------------
Remsen Ave & Ocean Ave N, Spring Lake, NJ

Pulls a 7-day wave/wind/water-temp forecast (Open-Meteo, free, no key),
tide predictions (NOAA CO-OPS, free, no key), and rip-current risk (NWS,
free, no key -- official for day 1 only, estimated beyond that), then
writes a single daily RSS item summarizing all 7 days.

Classification thresholds:
    Wave height:    1-2 ft   | 0.8-2.4 ft        | outside that
    Swell period:   8-12 sec | 6.0-8 or 12-14.4  | outside that
                    (floor widened from 6.4 to 6.0 sec per real-world
                    calibration -- a 6.2 sec reading on 2026-06-21 felt
                    fine in person, so the original floor was too strict)
    Wind speed:     <10 kt   | <12 kt            | >=12 kt
    Wind direction: 225-315 deg (SW-NW) | 207-333 deg | outside that

Rip-current risk note: NWS's official categorical call (Low/Moderate/
High) only covers ~1-2 days out -- there's no official multi-day
version. So only the nearest day in the feed gets the real NWS call;
days 2-7 get an estimate derived from the same height/period logic NWS
forecasters use, clearly labeled "(estimated)".

Run manually:
    pip3 install requests
    python3 fetch_and_build_feed.py
"""

import datetime
import os
import re
import xml.sax.saxutils as saxutils

import requests

# ---- Location & stations ----
LAT, LON = 40.1500, -74.0010
TIDE_STATION = "8532337"   # Belmar, NJ
RIP_RISK_ZONE = "NJZ014"   # Eastern Monmouth, incl. Sandy Hook -- uses Belmar tides too
TIMEZONE = "America/New_York"
FORECAST_DAYS = 7

OUTPUT_PATH = "docs/feed.xml"
FEED_TITLE = "Spring Lake Surf Conditions \u2014 Remsen Ave"
FEED_LINK = "https://example.com"  # replace with your GitHub Pages URL
FEED_DESC = "Daily 7-day surf forecast for Remsen Ave & Ocean Ave N, Spring Lake, NJ"

# ---- Classification thresholds ----
IDEAL_HEIGHT_FT = (1.0, 2.0)
INTERESTING_HEIGHT_FT = (0.8, 2.4)
IDEAL_PERIOD_SEC = (8.0, 12.0)
INTERESTING_PERIOD_SEC = (6.0, 14.4)   # floor widened from 6.4 -> 6.0
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
    idx = int((deg / 22.5) + 0.5) % 16
    return COMPASS_POINTS[idx]


MARINE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"
    "?latitude={lat}&longitude={lon}"
    "&hourly=wave_height,wave_period,wave_direction,sea_surface_temperature"
    "&length_unit=imperial&temperature_unit=fahrenheit&timezone={tz}&forecast_days={days}"
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
SRF_PRODUCTS_URL = "https://api.weather.gov/products/types/SRF/locations/PHI"


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


def fetch_official_rip_risk():
    """Best-effort fetch of today's official NWS rip-risk category for
    zone NJZ014. Returns None on any failure -- this is a nice-to-have,
    not allowed to break the rest of the feed if NWS's API hiccups."""
    try:
        r = requests.get(SRF_PRODUCTS_URL, timeout=20, headers={"User-Agent": "surf-agent (contact: n/a)"})
        r.raise_for_status()
        items = r.json().get("@graph", [])
        if not items:
            return None
        r2 = requests.get(items[0]["id"], timeout=20, headers={"User-Agent": "surf-agent (contact: n/a)"})
        r2.raise_for_status()
        text = r2.json().get("productText", "")
        idx = text.find(RIP_RISK_ZONE)
        if idx == -1:
            return None
        end_idx = text.find("$$", idx)
        segment = text[idx:end_idx if end_idx != -1 else None]
        m = re.search(r"Rip Current Risk\.+([A-Za-z]+)\.", segment)
        return m.group(1) if m else None
    except Exception:
        return None


def estimate_rip_risk(wave_ft, period_s):
    """Rough estimate for days beyond the official 1-2 day NWS horizon,
    using the same height/period relationship NWS forecasters cited for
    this coast (longer period and/or bigger surf -> higher risk)."""
    if period_s >= 13.0 or wave_ft >= 3.0:
        return "High"
    if period_s < 6.0 and wave_ft < 1.5:
        return "Low"
    return "Moderate"


def classify_value(value, ideal_ok, interesting_ok):
    if ideal_ok(value):
        return "IDEAL"
    if interesting_ok(value):
        return "INTERESTING"
    return "NOT IDEAL"


def classify_hour(h):
    """Returns (overall, h_class, p_class, w_class, d_class), or None if
    any required field is missing."""
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
    return overall, h_class, p_class, w_class, d_class


def explain_not_ideal(info):
    """Short human-readable reason(s) a day landed on NOT IDEAL."""
    reasons = []
    if info["h_class"] == "NOT IDEAL":
        if info["wave_ft"] < INTERESTING_HEIGHT_FT[0]:
            reasons.append(f"wave height too small ({info['wave_ft']:.1f} ft)")
        else:
            reasons.append(f"wave height too large ({info['wave_ft']:.1f} ft)")
    if info["p_class"] == "NOT IDEAL":
        if info["period_s"] < INTERESTING_PERIOD_SEC[0]:
            reasons.append(f"period too short ({info['period_s']:.1f} sec)")
        else:
            reasons.append(f"period too long ({info['period_s']:.1f} sec)")
    if info["w_class"] == "NOT IDEAL":
        reasons.append(f"wind too strong ({info['wind_kt']:.0f} kt)")
    if info["d_class"] == "NOT IDEAL":
        reasons.append(f"wind direction off ({degrees_to_compass(info['wind_dir'])})")
    return "; ".join(reasons) if reasons else "see stats"


def merge_and_classify(marine_json, wind_json, tide_json):
    times = marine_json["hourly"]["time"]
    wvht = marine_json["hourly"]["wave_height"]
    wper = marine_json["hourly"]["wave_period"]
    sst = marine_json["hourly"].get("sea_surface_temperature")  # may be absent

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
        result = classify_hour(h)
        if result is None:
            continue
        overall, h_c, p_c, w_c, d_c = result

        rank = RANK[overall]
        if date_str not in days or rank < days[date_str]["rank"]:
            days[date_str] = {
                "rank": rank, "class": overall, "hour": hour, **h,
                "h_class": h_c, "p_class": p_c, "w_class": w_c, "d_class": d_c,
                "water_temp_f": sst[i] if sst is not None else None,
            }

    lows_by_date = {}
    for p in tide_json.get("predictions", []):
        if p.get("type") == "L":
            d, tm = p["t"].split(" ")
            lows_by_date.setdefault(d, []).append(tm[:5])

    return days, lows_by_date


def build_rss(days, lows_by_date, official_rip_risk):
    now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    run_date = datetime.date.today().isoformat()
    sorted_dates = sorted(days.keys())

    tally = {"IDEAL": 0, "INTERESTING": 0, "NOT IDEAL": 0}
    text_lines = []
    html_lines = []

    for idx, date_str in enumerate(sorted_dates):
        info = days[date_str]
        tally[info["class"]] += 1
        lows = lows_by_date.get(date_str, [])
        low_str = ", ".join(lows) if lows else "n/a"
        badge = BADGE[info["class"]]
        wind_compass = degrees_to_compass(info["wind_dir"])
        dow = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")

        if idx == 0 and official_rip_risk:
            rip_str = f"{official_rip_risk} (NWS)"
        else:
            rip_str = f"{estimate_rip_risk(info['wave_ft'], info['period_s'])} (estimated)"

        temp_str = f", water {info['water_temp_f']:.0f}\u00b0F" if info.get("water_temp_f") is not None else ""

        line = (
            f"{dow} {date_str}: {badge} \u2014 best window {info['hour']:02d}:00, "
            f"{info['wave_ft']:.1f} ft @ {info['period_s']:.1f} sec, "
            f"wind {info['wind_kt']:.0f} kt {wind_compass}{temp_str}. "
            f"Low tide: {low_str}. Rip risk: {rip_str}."
        )
        if info["class"] == "NOT IDEAL":
            line += f" Why not ideal: {explain_not_ideal(info)}."

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
    official_rip_risk = fetch_official_rip_risk()

    days, lows = merge_and_classify(marine, wind, tides)
    xml = build_rss(days, lows, official_rip_risk)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(xml)

    print(f"Wrote {len(days)} day(s) to {OUTPUT_PATH}")
    print(f"Official NWS rip risk (day 1 only): {official_rip_risk}")
    for date_str in sorted(days.keys()):
        print(f"  {date_str}: {days[date_str]['class']}")


if __name__ == "__main__":
    main()
