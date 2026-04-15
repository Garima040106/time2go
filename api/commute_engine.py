import datetime as dt
import hashlib
import json
import math
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


SLOT_LABELS = ["Leave now", "+10 min", "+20 min", "+30 min"]
SLOT_OFFSETS_MIN = [0, 10, 20, 30]
USER_AGENT = "Time2GoHackathon/1.0 (contact: local-dev)"

# Keep outbound calls short so end-to-end latency stays below ~2 seconds.
GEO_TIMEOUT_SEC = 0.55
ROUTE_TIMEOUT_SEC = 0.55
WEATHER_TIMEOUT_SEC = 0.45
USE_ROUTE_API = os.getenv("TIME2GO_USE_ROUTE_API", "0").strip().lower() in {"1", "true", "yes"}

MODE_ALIASES = {
    "car": "driving",
    "cab": "driving",
    "taxi": "driving",
    "auto": "driving",
    "bike": "cycling",
    "cycle": "cycling",
    "cycling": "cycling",
    "walk": "foot",
    "foot": "foot",
    "bus": "driving",
    "metro": "driving",
}

MODE_BASE_SPEED_KMH = {
    "driving": 27.0,
    "cycling": 15.0,
    "foot": 5.0,
}

SAFE_MODE_OPTIONS = {"metro", "bus"}
ISOLATED_MODE_OPTIONS = {"car", "cab", "taxi", "auto", "bike", "cycle", "cycling"}

_GEOCODE_CACHE = {}
_WEATHER_CACHE = {}

HOTSPOT_PROFILES = [
    {
        "name": "Silk Board",
        "aliases": ["silk board", "silk board junction"],
        "stress_boost": 9,
        "driver": "Silk Board bottleneck is creating long merge queues",
    },
    {
        "name": "Outer Ring Road",
        "aliases": ["outer ring road", "orr", "bellandur orr", "marathahalli orr"],
        "stress_boost": 8,
        "driver": "ORR tech corridor rush is slowing this stretch",
    },
    {
        "name": "Whitefield",
        "aliases": ["whitefield", "itpl", "hope farm"],
        "stress_boost": 7,
        "driver": "Whitefield office corridor traffic is adding signal spillback",
    },
    {
        "name": "Electronic City",
        "aliases": ["electronic city", "ecity", "electronic city toll"],
        "stress_boost": 7,
        "driver": "Electronic City toll approach tends to bunch lanes",
    },
    {
        "name": "Marathahalli",
        "aliases": ["marathahalli", "marathahalli bridge", "marathahalli junction"],
        "stress_boost": 6,
        "driver": "Marathahalli junction weaving is adding stop-start delays",
    },
    {
        "name": "KR Puram",
        "aliases": ["kr puram", "krpuram", "tin factory"],
        "stress_boost": 6,
        "driver": "KR Puram interchange pressure is extending queue lengths",
    },
]


def _bounded(value, lower, upper):
    return max(lower, min(upper, value))


def _normalized_text(text):
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text or ""))
    return " ".join(cleaned.split())


def _stable_number(seed_text, lower, upper):
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    raw = int(digest[:8], 16)
    return lower + (raw % (upper - lower + 1))


def _detect_hotspots(origin, destination, origin_label=None, destination_label=None):
    combined = " ".join(
        [
            _normalized_text(origin),
            _normalized_text(destination),
            _normalized_text(origin_label),
            _normalized_text(destination_label),
        ]
    )
    if not combined:
        return []

    matches = []
    for profile in HOTSPOT_PROFILES:
        if any(alias in combined for alias in profile["aliases"]):
            matches.append(profile)

    matches.sort(key=lambda item: item["stress_boost"], reverse=True)
    return matches[:2]


def _is_weekday_peak(hour):
    return 7.0 <= hour <= 10.0 or 17.0 <= hour <= 20.0


def _is_weekday_peak_dt(base_dt):
    if base_dt.weekday() >= 5:
        return False
    hour = base_dt.hour + base_dt.minute / 60.0
    return _is_weekday_peak(hour)


def _hotspot_stress_boost(hotspots, departure_dt, is_weekend):
    if not hotspots:
        return 0

    hour = departure_dt.hour + departure_dt.minute / 60.0
    base = min(14, sum(item["stress_boost"] for item in hotspots))

    if is_weekend:
        factor = 0.8 if 11.0 <= hour <= 21.0 else 0.65
    else:
        factor = 1.0 if _is_weekday_peak(hour) else 0.72

    return int(round(base * factor))


def _is_common_office_route(origin, destination, origin_label, destination_label, hotspots, distance_km):
    combined = " ".join(
        [
            _normalized_text(origin),
            _normalized_text(destination),
            _normalized_text(origin_label),
            _normalized_text(destination_label),
        ]
    )

    corridor_keywords = {
        "tech park",
        "it park",
        "business park",
        "office",
        "manyata",
        "bagmane",
        "ecoworld",
        "ecospace",
        "itpl",
        "electronic city",
        "whitefield",
        "bellandur",
        "marathahalli",
        "outer ring road",
        "orr",
    }

    keyword_hit = any(token in combined for token in corridor_keywords)
    hotspot_hit = len(hotspots) > 0
    reasonable_commute = 4.0 <= distance_km <= 35.0
    return reasonable_commute and (keyword_hit or hotspot_hit)


def _carpool_stress_adjustment(carpool_possible):
    return -2 if carpool_possible else 0


def _carpool_note(carpool_possible):
    return "carpool friendly" if carpool_possible else ""


def _generic_location_signal(origin_label, destination_label, distance_km):
    seed = _stable_number(f"{origin_label}|{destination_label}|{distance_km:.1f}", 0, 2)
    if seed == 0:
        return "Local junction chaining is adding short stop-go pockets"
    if seed == 1:
        return "Mixed arterial traffic is causing uneven signal clearances"
    return "Urban corridor pressure is creating intermittent bottlenecks"


def _same_place_hint(origin, destination):
    left = _normalized_text(origin)
    right = _normalized_text(destination)
    return bool(left) and left == right


def _is_quiet_window(base_dt):
    hour = base_dt.hour + (base_dt.minute / 60.0)
    return hour >= 22.0 or hour < 7.0


def _minimal_eta_minutes(distance_km, mode_profile):
    speed_kmh = MODE_BASE_SPEED_KMH.get(mode_profile, 25.0)
    moving_min = max(1.0, (max(distance_km, 0.35) / max(speed_kmh, 3.0)) * 60.0)
    return int(_bounded(round(moving_min + 2.0), 3, 12))


def _build_low_traffic_result(route_label, raw_mode, mode_profile, distance_km, condition_label, base_dt):
    base_eta = _minimal_eta_minutes(distance_km, mode_profile)
    slots = []

    for idx, label in enumerate(SLOT_LABELS):
        departure_dt = base_dt + dt.timedelta(minutes=SLOT_OFFSETS_MIN[idx])
        traffic_level = "low"
        safety_risk = _estimate_safety_risk(departure_dt, raw_mode, mode_profile, distance_km, traffic_level)
        safety_note = _safety_note(safety_risk, departure_dt, raw_mode, traffic_level)
        eta_min = int(_bounded(base_eta + (1 if idx >= 2 else 0), 3, 12))
        slots.append(
            {
                "label": label,
                "stress": 9 + idx + _safety_stress_bump(safety_risk),
                "eta_min": eta_min,
                "traffic_level": traffic_level,
                "note": _merge_slot_note("smooth ride", safety_note),
                "safety_risk": safety_risk,
                "safety_note": safety_note,
            }
        )

    if condition_label == "same_place":
        reason = "Origin and destination are essentially the same. You can leave immediately."
        drivers = [
            "No meaningful commute segment detected on this route",
            "Local movement only; traffic impact is minimal right now",
        ]
    elif condition_label == "very_short":
        reason = "This is a short hop with light traffic. Leaving now is best."
        drivers = [
            "Short distance keeps travel time and stress low",
            "Nearby route has minimal junction exposure right now",
        ]
    elif condition_label == "late_night":
        reason = "Late-night roads are clear. Leave now for the smoothest run."
        drivers = [
            "Off-peak late-night window reduces stop-go friction",
            "Lower vehicle density is keeping this corridor open",
        ]
    else:
        reason = "Early roads are still clear. Leave now before activity builds."
        drivers = [
            "Early-morning traffic is light across main connectors",
            "Signal cycles are clearing quickly at this hour",
        ]

    return {
        "route": route_label,
        "slots": slots,
        "recommendation": "Leave now",
        "reason": reason,
        "stress_drivers": drivers,
    }


def _fetch_json(base_url, params, timeout_sec=1.0):
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{base_url}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _short_place(label):
    if not label:
        return "this route"
    return label.split(",")[0].strip() or label.strip()


def _parse_current_datetime(current_time, day_type):
    now = dt.datetime.now()
    try:
        hour_str, minute_str = current_time.strip().split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        hour = _bounded(hour, 0, 23)
        minute = _bounded(minute, 0, 59)
    except (AttributeError, ValueError):
        hour = now.hour
        minute = now.minute

    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target_weekend = str(day_type).strip().lower() == "weekend"

    for _ in range(7):
        is_weekend = base.weekday() >= 5
        if is_weekend == target_weekend:
            break
        base += dt.timedelta(days=1)

    return base


def _geocode_place(place):
    cache_key = str(place or "").strip().lower()
    if cache_key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[cache_key]

    data = _fetch_json(
        "https://nominatim.openstreetmap.org/search",
        {
            "q": place,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
        },
        timeout_sec=GEO_TIMEOUT_SEC,
    )

    if not data:
        _GEOCODE_CACHE[cache_key] = None
        return None

    first = data[0]
    result = {
        "lat": float(first["lat"]),
        "lon": float(first["lon"]),
        "label": first.get("display_name", place),
    }
    _GEOCODE_CACHE[cache_key] = result
    return result


def _haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_route(origin_geo, dest_geo, mode):
    profile = MODE_ALIASES.get(mode.lower(), "driving")
    coord = f"{origin_geo['lon']},{origin_geo['lat']};{dest_geo['lon']},{dest_geo['lat']}"
    endpoint = f"https://router.project-osrm.org/route/v1/{profile}/{coord}"

    data = _fetch_json(
        endpoint,
        {
            "overview": "false",
            "alternatives": "false",
            "steps": "false",
        },
        timeout_sec=ROUTE_TIMEOUT_SEC,
    )

    routes = data.get("routes", [])
    if not routes:
        raise ValueError("No route from OSRM")

    route = routes[0]
    return {
        "distance_km": route["distance"] / 1000.0,
        "duration_min": route["duration"] / 60.0,
        "profile": profile,
    }


def _nearest_hour_index(hourly_times, target_time):
    nearest = None
    nearest_diff = None
    for idx, text in enumerate(hourly_times):
        try:
            value = dt.datetime.fromisoformat(text)
        except ValueError:
            continue
        diff = abs((value - target_time).total_seconds())
        if nearest_diff is None or diff < nearest_diff:
            nearest = idx
            nearest_diff = diff
    return nearest


def _fetch_weather(lat, lon, target_time):
    cache_key = _weather_cache_key(lat, lon, target_time)
    if cache_key in _WEATHER_CACHE:
        return dict(_WEATHER_CACHE[cache_key])

    data = _fetch_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": f"{lat:.5f}",
            "longitude": f"{lon:.5f}",
            "hourly": [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "weather_code",
            ],
            "forecast_days": 2,
            "timezone": "auto",
        },
        timeout_sec=WEATHER_TIMEOUT_SEC,
    )

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    idx = _nearest_hour_index(times, target_time)
    if idx is None:
        raise ValueError("No matching weather hour")

    result = {
        "temperature_c": float(hourly.get("temperature_2m", [25])[idx]),
        "precip_prob": float(hourly.get("precipitation_probability", [0])[idx]),
        "precip_mm": float(hourly.get("precipitation", [0])[idx]),
        "wind_kph": float(hourly.get("wind_speed_10m", [8])[idx]),
        "weather_code": int(hourly.get("weather_code", [0])[idx]),
    }
    _WEATHER_CACHE[cache_key] = result
    return dict(result)


def _weather_cache_key(lat, lon, target_time):
    hour_key = target_time.replace(minute=0, second=0, microsecond=0).isoformat()
    return f"{lat:.3f}|{lon:.3f}|{hour_key}"


def _weather_penalty(weather):
    penalty = 0.0
    penalty += _bounded(weather.get("precip_prob", 0) / 100.0, 0, 1) * 0.35
    penalty += _bounded(weather.get("precip_mm", 0) / 6.0, 0, 1) * 0.25

    temp = weather.get("temperature_c", 25)
    if temp > 34:
        penalty += _bounded((temp - 34) / 10.0, 0, 0.2)
    if temp < 10:
        penalty += _bounded((10 - temp) / 15.0, 0, 0.2)

    wind = weather.get("wind_kph", 0)
    penalty += _bounded((wind - 20) / 40.0, 0, 0.2)
    return _bounded(penalty, 0, 0.8)


def _congestion_curve(departure_dt, is_weekend):
    hour = departure_dt.hour + departure_dt.minute / 60.0

    if is_weekend:
        midday = math.exp(-((hour - 13.0) ** 2) / (2 * (2.2 ** 2)))
        evening = math.exp(-((hour - 19.0) ** 2) / (2 * (2.0 ** 2)))
        return _bounded(0.15 + 0.45 * max(midday, evening), 0.05, 0.95)

    morning = math.exp(-((hour - 8.8) ** 2) / (2 * (1.45 ** 2)))
    evening = math.exp(-((hour - 18.3) ** 2) / (2 * (1.75 ** 2)))
    school_pickup = math.exp(-((hour - 15.8) ** 2) / (2 * (1.0 ** 2)))
    return _bounded(0.2 + 0.62 * max(morning, evening) + 0.08 * school_pickup, 0.08, 0.98)


def _trend_direction(base_dt, is_weekend):
    current = _congestion_curve(base_dt, is_weekend)
    plus_half_hour = _congestion_curve(base_dt + dt.timedelta(minutes=30), is_weekend)
    return 1 if plus_half_hour >= current else -1


def _estimate_distance_without_route(origin, destination):
    same_city_hint = False
    origin_parts = [part.strip().lower() for part in origin.split(",") if part.strip()]
    dest_parts = [part.strip().lower() for part in destination.split(",") if part.strip()]
    if len(origin_parts) > 1 and len(dest_parts) > 1 and origin_parts[-1] == dest_parts[-1]:
        same_city_hint = True

    seed = _stable_number(f"{origin}|{destination}", 0, 100)
    if same_city_hint:
        return 5.0 + (seed % 15)
    return 12.0 + (seed % 30)


def _simulate_weather(target_time):
    month = target_time.month
    hour = target_time.hour

    is_monsoon = month in {6, 7, 8, 9}
    is_summer = month in {3, 4, 5}
    is_winter = month in {11, 12, 1}

    if is_monsoon and (14 <= hour <= 22):
        return {
            "temperature_c": 27.0,
            "precip_prob": 72.0,
            "precip_mm": 2.1,
            "wind_kph": 16.0,
            "weather_code": 61,
        }

    if is_summer and (11 <= hour <= 17):
        return {
            "temperature_c": 37.0,
            "precip_prob": 8.0,
            "precip_mm": 0.0,
            "wind_kph": 11.0,
            "weather_code": 1,
        }

    if is_winter and (5 <= hour <= 8):
        return {
            "temperature_c": 16.0,
            "precip_prob": 12.0,
            "precip_mm": 0.0,
            "wind_kph": 6.0,
            "weather_code": 3,
        }

    return {
        "temperature_c": 29.0,
        "precip_prob": 14.0,
        "precip_mm": 0.0,
        "wind_kph": 9.0,
        "weather_code": 0,
    }


def _weather_note(weather, weather_penalty):
    if weather.get("precip_prob", 0) >= 45 or weather.get("precip_mm", 0) >= 0.8 or weather_penalty >= 0.45:
        return "wet roads"
    if weather.get("temperature_c", 0) >= 35:
        return "slow traffic"
    return "smooth ride"


def _mode_safety_weight(raw_mode, mode_profile):
    mode_key = str(raw_mode or "").strip().lower()
    if mode_key in {"bus", "metro"}:
        return -1
    if mode_key in {"bike", "cycle", "cycling", "car", "cab", "taxi", "auto"}:
        return 1
    if mode_profile == "foot":
        return 1
    return 0


def _estimate_safety_risk(departure_dt, raw_mode, mode_profile, distance_km, traffic_level):
    score = 0
    hour = departure_dt.hour + departure_dt.minute / 60.0

    # Late windows trend slightly higher due to lower public activity.
    if hour >= 22.0 or hour < 5.0:
        score += 2
    elif 5.0 <= hour < 7.0 or 20.5 <= hour < 22.0:
        score += 1

    score += _mode_safety_weight(raw_mode, mode_profile)

    # Longer, lighter-traffic segments can feel more isolated.
    if distance_km >= 14.0:
        score += 1
    if distance_km >= 24.0 and traffic_level == "low":
        score += 1

    if traffic_level == "high":
        score -= 1

    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _safety_note(safety_risk, departure_dt, raw_mode, traffic_level):
    if safety_risk == "low":
        if traffic_level in {"medium", "high"} and str(raw_mode or "").strip().lower() in {"bus", "metro"}:
            return "crowded commute"
        return "well-lit route"

    hour = departure_dt.hour + departure_dt.minute / 60.0
    if safety_risk == "high" and (hour >= 22.0 or hour < 5.0):
        return "late hour risk"
    if traffic_level in {"medium", "high"}:
        return "crowded commute"
    return "late hour risk" if safety_risk == "high" else "well-lit route"


def _merge_slot_note(base_note, safety_note):
    if not safety_note:
        return base_note
    if base_note == safety_note:
        return base_note
    return f"{base_note}; {safety_note}"


def _safety_stress_bump(safety_risk):
    return 4 if safety_risk == "high" else 0


def _apply_safe_mode_preference(raw_mode, prefer_safe_commute, distance_km):
    mode_key = str(raw_mode or "").strip().lower()
    if not prefer_safe_commute:
        return mode_key
    if mode_key in SAFE_MODE_OPTIONS:
        return mode_key
    if mode_key in ISOLATED_MODE_OPTIONS:
        return "metro" if distance_km >= 7.0 else "bus"
    return mode_key


def _safe_mode_stress_adjustment(prefer_safe_commute, active_mode):
    if prefer_safe_commute and active_mode in SAFE_MODE_OPTIONS:
        return -3
    return 0


def _preferred_commute_note(prefer_safe_commute, active_mode):
    if prefer_safe_commute and active_mode in SAFE_MODE_OPTIONS:
        return "safer commute option"
    return ""


def _classify_traffic_level(traffic_score):
    if traffic_score >= 0.68:
        return "high"
    if traffic_score >= 0.4:
        return "medium"
    return "low"


def _time_of_day_weight(departure_dt, is_weekend, congestion):
    hour = departure_dt.hour + departure_dt.minute / 60.0
    weight = 6.0 + (24.0 * congestion)

    if is_weekend:
        if 11.0 <= hour <= 21.0:
            weight += 5.0
    else:
        if 7.0 <= hour <= 10.0 or 17.0 <= hour <= 20.0:
            weight += 12.0

    return weight


def _mode_penalty(mode_profile):
    return {
        "driving": 12.0,
        "cycling": 7.0,
        "foot": 4.0,
    }.get(mode_profile, 10.0)


def _traffic_level_weight(traffic_level, mode_profile):
    base = {
        "low": 6.0,
        "medium": 14.0,
        "high": 22.0,
    }.get(traffic_level, 11.0)

    # Bikes and walkers generally feel less stress in congested traffic than cars.
    sensitivity = {
        "driving": 1.0,
        "cycling": 0.7,
        "foot": 0.5,
    }.get(mode_profile, 0.9)
    return base * sensitivity


def _weather_weight(weather, weather_penalty):
    weight = weather_penalty * 22.0
    precip_prob = weather.get("precip_prob", 0.0)
    precip_mm = weather.get("precip_mm", 0.0)

    # Rain should have a clear stress impact.
    if precip_prob >= 45.0 or precip_mm >= 0.8:
        weight += 16.0
    if precip_prob >= 70.0 or precip_mm >= 2.0:
        weight += 8.0

    return weight


def _route_complexity_weight(distance_km, congestion):
    return 4.0 + min(distance_km, 45.0) * 0.25 + (4.0 * congestion)


def _api_traffic_signal(distance_km, base_duration_min, mode_profile):
    if distance_km <= 0.1:
        return None

    baseline_speed = MODE_BASE_SPEED_KMH.get(mode_profile, 25.0)
    api_speed = distance_km / max(base_duration_min / 60.0, 0.01)
    ratio = baseline_speed / max(api_speed, 1.0)
    normalized = _bounded((ratio - 0.75) / 1.25, 0.0, 1.0)
    return normalized


def _estimate_traffic_score(departure_dt, is_weekend, distance_km, api_signal=None):
    peak = _congestion_curve(departure_dt, is_weekend)
    hour = departure_dt.hour + departure_dt.minute / 60.0

    if is_weekend:
        hour_bias = 0.08 if 11.0 <= hour <= 21.0 else -0.03
    else:
        hour_bias = 0.16 if (7.0 <= hour <= 10.0 or 17.0 <= hour <= 20.0) else -0.02

    length_bias = _bounded((distance_km - 8.0) / 35.0, 0.0, 0.26)
    fallback_score = _bounded(0.52 * peak + 0.3 + hour_bias + length_bias, 0.05, 0.97)
    if api_signal is None:
        return fallback_score

    return _bounded((0.58 * fallback_score) + (0.42 * api_signal), 0.05, 0.98)


def _human_drivers(origin_label, destination_label, weather, is_weekend, distance_km, hotspots):
    origin_short = _short_place(origin_label)
    destination_short = _short_place(destination_label)
    drivers = []

    if is_weekend:
        drivers.append(f"Leisure traffic around {destination_short} can bunch up signals")
    else:
        drivers.append(f"Office-hour pressure near {origin_short} funnels into main junctions")

    if hotspots:
        drivers.extend([item["driver"] for item in hotspots])
    else:
        drivers.append(_generic_location_signal(origin_label, destination_label, distance_km))

    if weather.get("precip_prob", 0) >= 45 or weather.get("precip_mm", 0) >= 0.8:
        drivers.append("Wet roads and cautious braking usually add stop-start delays")
    elif weather.get("temperature_c", 25) >= 35:
        drivers.append("Heat haze often slows two-wheelers and bus lane merges")
    else:
        drivers.append(f"{distance_km:.1f} km corridor keeps stress sensitive to small signal delays")

    return drivers[:3]


def _choose_recommendation(slots):
    now_stress = slots[0]["stress"]
    best_idx = min(range(len(slots)), key=lambda i: slots[i]["stress"])
    best_stress = slots[best_idx]["stress"]
    improvement = now_stress - best_stress

    # Keep advice human and decisive: tiny gains should not ask people to wait.
    if best_idx == 0 or improvement <= 5:
        recommendation = "Leave now"
        reason = "Traffic looks stable now. Waiting offers little benefit."
        return recommendation, reason, best_idx

    wait_minutes = best_idx * 10
    if improvement >= 10:
        recommendation = f"Wait {wait_minutes} minutes"
        reason = f"A brief wait should noticeably reduce traffic stress on this route."
        return recommendation, reason, best_idx

    recommendation = "Delay slightly for smoother ride"
    reason = "Short delay should smooth this stretch with minimal arrival impact."
    return recommendation, reason, best_idx


def _build_time_insight(slots):
    if not slots:
        return "Leave in your recommended slot for the best balance of stress and ETA."

    now_eta = slots[0].get("eta_min", 0)
    best_idx = min(range(len(slots)), key=lambda i: slots[i].get("stress", 100))
    best_slot = slots[best_idx]
    best_eta = best_slot.get("eta_min", now_eta)
    wait_minutes = best_idx * 10
    arrival_delta = (wait_minutes + best_eta) - now_eta

    if best_idx == 0:
        return "Current window is already the best balance for this route."
    if arrival_delta <= 2:
        return f"Waiting {wait_minutes} minutes is likely to keep arrival time nearly unchanged."
    if arrival_delta < 0:
        return f"Waiting {wait_minutes} minutes may still save about {abs(arrival_delta)} minutes overall."
    return f"Leaving now can save roughly {arrival_delta} minutes versus waiting {wait_minutes} minutes."


def _eta_from_duration(duration_min, congestion, weather_penalty, mode_profile, traffic_level):
    mode_overhead = 0.07 if mode_profile == "driving" else 0.03 if mode_profile == "cycling" else 0.0
    multiplier = 0.88 + (0.74 * congestion) + (0.35 * weather_penalty) + mode_overhead
    traffic_bump = {"low": 0.02, "medium": 0.07, "high": 0.14}.get(traffic_level, 0.04)
    return max(4, int(round(duration_min * (multiplier + traffic_bump))))


def _stress_score(
    departure_dt,
    is_weekend,
    congestion,
    weather,
    weather_penalty,
    distance_km,
    mode_profile,
    traffic_level,
):
    score = (
        _time_of_day_weight(departure_dt, is_weekend, congestion)
        + _mode_penalty(mode_profile)
        + _traffic_level_weight(traffic_level, mode_profile)
        + _weather_weight(weather, weather_penalty)
        + _route_complexity_weight(distance_km, congestion)
    )
    return int(round(_bounded(score, 0, 100)))


def _enforce_slot_contrast(slots):
    if not slots:
        return

    best_idx = min(range(len(slots)), key=lambda i: slots[i]["stress"])
    best_stress = slots[best_idx]["stress"]

    # Keep one clearly optimal slot and ensure visible spread for all options.
    for idx, slot in enumerate(slots):
        if idx == best_idx:
            continue

        distance = abs(idx - best_idx)
        min_target = best_stress + 8 + (distance * 2)
        if slot["stress"] < min_target:
            slot["stress"] = min_target

    seen = set()
    for idx, slot in enumerate(slots):
        value = int(_bounded(slot["stress"], 0, 100))
        while value in seen and value < 100:
            value += 1
        # If we hit 100 with collisions, walk backward to stay unique in range.
        while value in seen and value > 0:
            value -= 1
        slot["stress"] = value
        seen.add(value)


def analyze_commute(origin, destination, mode, day_type, current_time, prefer_safe_commute=False):
    base_dt = _parse_current_datetime(current_time, day_type)
    is_weekend = base_dt.weekday() >= 5
    used_live_route = False

    origin_geo = None
    dest_geo = None
    if USE_ROUTE_API:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_origin = pool.submit(_geocode_place, origin)
            fut_dest = pool.submit(_geocode_place, destination)
            try:
                origin_geo = fut_origin.result(timeout=0.9)
            except Exception:
                origin_geo = None
            try:
                dest_geo = fut_dest.result(timeout=0.9)
            except Exception:
                dest_geo = None

    # Weather should be based on origin point; fetch quickly and fall back deterministically.
    weather_origin_geo = origin_geo
    if weather_origin_geo is None:
        try:
            weather_origin_geo = _geocode_place(origin)
        except Exception:
            weather_origin_geo = None

    route = None
    weather = _simulate_weather(base_dt)

    raw_mode = mode.lower()
    mode_profile = MODE_ALIASES.get(raw_mode, "driving")

    if origin_geo and dest_geo:
        try:
            route = _get_route(origin_geo, dest_geo, mode)
            used_live_route = True
        except Exception:
            route = None

    if weather_origin_geo:
        try:
            weather = _fetch_weather(weather_origin_geo["lat"], weather_origin_geo["lon"], base_dt)
        except Exception:
            weather = _simulate_weather(base_dt)
            _WEATHER_CACHE[_weather_cache_key(weather_origin_geo["lat"], weather_origin_geo["lon"], base_dt)] = dict(weather)

    if route:
        distance_km = route["distance_km"]
        base_duration_min = route["duration_min"]
    elif origin_geo and dest_geo:
        crow_km = _haversine_km(origin_geo["lat"], origin_geo["lon"], dest_geo["lat"], dest_geo["lon"])
        distance_km = max(0.6, crow_km * 1.35)
        speed_kmh = MODE_BASE_SPEED_KMH.get(mode_profile, 25.0)
        base_duration_min = (distance_km / speed_kmh) * 60.0
    else:
        if _same_place_hint(origin, destination):
            distance_km = 0.5
        else:
            distance_km = _estimate_distance_without_route(origin, destination)
        speed_kmh = MODE_BASE_SPEED_KMH.get(mode_profile, 25.0)
        base_duration_min = (distance_km / speed_kmh) * 60.0

    origin_label = origin_geo["label"] if origin_geo else origin
    destination_label = dest_geo["label"] if dest_geo else destination
    route_label = f"{_short_place(origin_label)} -> {_short_place(destination_label)}"
    active_mode = _apply_safe_mode_preference(raw_mode, prefer_safe_commute, distance_km)
    active_mode_profile = MODE_ALIASES.get(active_mode, mode_profile)
    hotspots = _detect_hotspots(origin, destination, origin_label, destination_label)
    carpool_possible = _is_weekday_peak_dt(base_dt) and _is_common_office_route(
        origin,
        destination,
        origin_label,
        destination_label,
        hotspots,
        distance_km,
    )

    same_place = _same_place_hint(origin_label, destination_label)
    very_short = distance_km <= 2.2
    quiet_window = _is_quiet_window(base_dt)
    if same_place or very_short or quiet_window:
        if same_place:
            condition_label = "same_place"
        elif very_short:
            condition_label = "very_short"
        elif base_dt.hour >= 22 or base_dt.hour < 4:
            condition_label = "late_night"
        else:
            condition_label = "early_morning"

        quick_result = _build_low_traffic_result(route_label, active_mode, active_mode_profile, distance_km, condition_label, base_dt)
        stress_adjust = _safe_mode_stress_adjustment(prefer_safe_commute, active_mode)
        preference_note = _preferred_commute_note(prefer_safe_commute, active_mode)
        if stress_adjust or preference_note:
            for slot in quick_result["slots"]:
                if stress_adjust:
                    slot["stress"] = int(_bounded(slot["stress"] + stress_adjust, 0, 100))
                if preference_note:
                    slot["note"] = _merge_slot_note(slot["note"], preference_note)
        if carpool_possible:
            for slot in quick_result["slots"]:
                slot["stress"] = int(_bounded(slot["stress"] + _carpool_stress_adjustment(True), 0, 100))
                slot["note"] = _merge_slot_note(slot["note"], _carpool_note(True))
            quick_result["carpool_suggestion"] = "High chance of shared rides on this route"
        quick_result["time_insight"] = _build_time_insight(quick_result["slots"])
        quick_result["prefer_safe_commute"] = bool(prefer_safe_commute)
        return quick_result

    weather_penalty = _weather_penalty(weather)
    api_signal = _api_traffic_signal(distance_km, base_duration_min, mode_profile) if route else None
    slots = []
    for idx, minutes in enumerate(SLOT_OFFSETS_MIN):
        departure_dt = base_dt + dt.timedelta(minutes=minutes)
        congestion = _congestion_curve(departure_dt, is_weekend)
        traffic_score = _estimate_traffic_score(departure_dt, is_weekend, distance_km, api_signal)
        traffic_level = _classify_traffic_level(traffic_score)
        safety_risk = _estimate_safety_risk(departure_dt, raw_mode, mode_profile, distance_km, traffic_level)
        safety_note = _safety_note(safety_risk, departure_dt, active_mode, traffic_level)
        stress = _stress_score(
            departure_dt,
            is_weekend,
            congestion,
            weather,
            weather_penalty,
            distance_km,
            active_mode_profile,
            traffic_level,
        )
        stress += _hotspot_stress_boost(hotspots, departure_dt, is_weekend)
        stress += _safety_stress_bump(safety_risk)
        stress += _safe_mode_stress_adjustment(prefer_safe_commute, active_mode)
        stress += _carpool_stress_adjustment(carpool_possible)
        eta_min = _eta_from_duration(base_duration_min, congestion, weather_penalty, active_mode_profile, traffic_level)
        note_base = _weather_note(weather, weather_penalty)
        preference_note = _preferred_commute_note(prefer_safe_commute, active_mode)
        carpool_note = _carpool_note(carpool_possible)

        slots.append(
            {
                "label": SLOT_LABELS[idx],
                "stress": stress,
                "eta_min": eta_min,
                "traffic_level": traffic_level,
                "note": _merge_slot_note(
                    _merge_slot_note(_merge_slot_note(note_base, safety_note), preference_note),
                    carpool_note,
                ),
                "safety_risk": safety_risk,
                "safety_note": safety_note,
            }
        )

    _enforce_slot_contrast(slots)

    recommendation, reason, best_idx = _choose_recommendation(slots)

    drivers = _human_drivers(origin_label, destination_label, weather, is_weekend, distance_km, hotspots)
    if used_live_route:
        drivers.insert(0, "Traffic level blended with live route-speed signal")
    else:
        drivers.insert(0, "Traffic level estimated from hour, peak pattern, route length and day type")

    result = {
        "route": route_label,
        "slots": slots,
        "recommendation": recommendation,
        "reason": reason,
        "stress_drivers": drivers,
        "time_insight": _build_time_insight(slots),
        "prefer_safe_commute": bool(prefer_safe_commute),
    }

    if carpool_possible:
        result["carpool_suggestion"] = "High chance of shared rides on this route"

    return result
