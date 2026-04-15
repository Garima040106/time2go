import datetime as dt
import hashlib
import json
import math
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


SLOT_LABELS = ["Leave now", "+10 min", "+20 min", "+30 min"]
SLOT_OFFSETS_MIN = [0, 10, 20, 30]
USER_AGENT = "Time2GoHackathon/1.0 (contact: local-dev)"

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


def _bounded(value, lower, upper):
    return max(lower, min(upper, value))


def _stable_number(seed_text, lower, upper):
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    raw = int(digest[:8], 16)
    return lower + (raw % (upper - lower + 1))


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
    data = _fetch_json(
        "https://nominatim.openstreetmap.org/search",
        {
            "q": place,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
        },
        timeout_sec=1.2,
    )

    if not data:
        return None

    first = data[0]
    return {
        "lat": float(first["lat"]),
        "lon": float(first["lon"]),
        "label": first.get("display_name", place),
    }


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
        timeout_sec=1.2,
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
        timeout_sec=1.2,
    )

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    idx = _nearest_hour_index(times, target_time)
    if idx is None:
        raise ValueError("No matching weather hour")

    return {
        "temperature_c": float(hourly.get("temperature_2m", [25])[idx]),
        "precip_prob": float(hourly.get("precipitation_probability", [0])[idx]),
        "precip_mm": float(hourly.get("precipitation", [0])[idx]),
        "wind_kph": float(hourly.get("wind_speed_10m", [8])[idx]),
        "weather_code": int(hourly.get("weather_code", [0])[idx]),
    }


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


def _slot_note(congestion, weather_penalty):
    if weather_penalty > 0.45:
        return "Rain slows lanes"
    if congestion > 0.75:
        return "Rush crunch"
    if congestion > 0.55:
        return "Busy junctions"
    if congestion < 0.3:
        return "Roads easing"
    return "Steady flow"


def _human_drivers(origin_label, destination_label, weather, is_weekend, distance_km):
    origin_short = _short_place(origin_label)
    destination_short = _short_place(destination_label)
    drivers = []

    if is_weekend:
        drivers.append(f"Leisure traffic around {destination_short} can bunch up signals")
    else:
        drivers.append(f"Office-hour pressure near {origin_short} funnels into main junctions")

    if weather.get("precip_prob", 0) >= 45 or weather.get("precip_mm", 0) >= 0.8:
        drivers.append("Wet roads and cautious braking usually add stop-start delays")
    elif weather.get("temperature_c", 25) >= 35:
        drivers.append("Heat haze often slows two-wheelers and bus lane merges")
    else:
        drivers.append(f"{distance_km:.1f} km corridor keeps stress sensitive to small signal delays")

    return drivers[:3]


def _build_reason(best_idx, best_stress, slots):
    if best_idx == 0:
        return f"Current window is calmest with stress {best_stress}; waiting likely runs into denser signal cycles."

    next_label = slots[best_idx]["label"].lower()
    return f"{next_label} avoids the sharpest congestion pocket while keeping travel time stable."


def _eta_from_duration(duration_min, congestion, weather_penalty, mode_profile):
    mode_overhead = 0.07 if mode_profile == "driving" else 0.03 if mode_profile == "cycling" else 0.0
    multiplier = 0.88 + (0.74 * congestion) + (0.35 * weather_penalty) + mode_overhead
    return max(4, int(round(duration_min * multiplier)))


def _stress_score(congestion, weather_penalty, distance_km, mode_profile):
    mode_load = {"driving": 7.0, "cycling": 4.0, "foot": 2.0}.get(mode_profile, 6.0)
    distance_load = _bounded(distance_km / 20.0, 0, 1.6) * 14.0

    score = (
        18.0
        + (congestion * 44.0)
        + (weather_penalty * 24.0)
        + distance_load
        + mode_load
    )
    return int(round(_bounded(score, 8, 97)))


def analyze_commute(origin, destination, mode, day_type, current_time):
    base_dt = _parse_current_datetime(current_time, day_type)
    is_weekend = base_dt.weekday() >= 5

    origin_geo = None
    dest_geo = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_origin = pool.submit(_geocode_place, origin)
        fut_dest = pool.submit(_geocode_place, destination)
        try:
            origin_geo = fut_origin.result(timeout=1.5)
        except Exception:
            origin_geo = None
        try:
            dest_geo = fut_dest.result(timeout=1.5)
        except Exception:
            dest_geo = None

    route = None
    weather = {
        "temperature_c": 27.0,
        "precip_prob": 0.0,
        "precip_mm": 0.0,
        "wind_kph": 8.0,
        "weather_code": 0,
    }

    mode_profile = MODE_ALIASES.get(mode.lower(), "driving")

    if origin_geo and dest_geo:
        try:
            route = _get_route(origin_geo, dest_geo, mode)
        except Exception:
            route = None

    if route:
        distance_km = route["distance_km"]
        base_duration_min = route["duration_min"]
    elif origin_geo and dest_geo:
        crow_km = _haversine_km(origin_geo["lat"], origin_geo["lon"], dest_geo["lat"], dest_geo["lon"])
        distance_km = max(2.0, crow_km * 1.35)
        speed_kmh = MODE_BASE_SPEED_KMH.get(mode_profile, 25.0)
        base_duration_min = (distance_km / speed_kmh) * 60.0
    else:
        distance_km = _estimate_distance_without_route(origin, destination)
        speed_kmh = MODE_BASE_SPEED_KMH.get(mode_profile, 25.0)
        base_duration_min = (distance_km / speed_kmh) * 60.0

    if origin_geo and dest_geo:
        midpoint_lat = (origin_geo["lat"] + dest_geo["lat"]) / 2.0
        midpoint_lon = (origin_geo["lon"] + dest_geo["lon"]) / 2.0
        try:
            weather = _fetch_weather(midpoint_lat, midpoint_lon, base_dt)
        except Exception:
            pass

    weather_penalty = _weather_penalty(weather)
    trend = _trend_direction(base_dt, is_weekend)

    slots = []
    stresses = []
    for idx, minutes in enumerate(SLOT_OFFSETS_MIN):
        departure_dt = base_dt + dt.timedelta(minutes=minutes)
        congestion = _congestion_curve(departure_dt, is_weekend)
        stress = _stress_score(congestion, weather_penalty, distance_km, mode_profile)
        eta_min = _eta_from_duration(base_duration_min, congestion, weather_penalty, mode_profile)

        slots.append(
            {
                "label": SLOT_LABELS[idx],
                "stress": stress,
                "eta_min": eta_min,
                "note": _slot_note(congestion, weather_penalty),
            }
        )
        stresses.append(stress)

    spread = max(stresses) - min(stresses)
    if spread < 6:
        for idx, slot in enumerate(slots):
            adjust = int(round((idx - 1.5) * 2.5 * trend))
            slot["stress"] = int(_bounded(slot["stress"] + adjust, 6, 98))
            slot["eta_min"] = max(4, slot["eta_min"] + int(round(adjust / 4)))

    best_idx = min(range(len(slots)), key=lambda i: slots[i]["stress"])
    recommendation = "Leave now" if best_idx == 0 else f"Leave in {best_idx * 10} minutes"

    origin_label = origin_geo["label"] if origin_geo else origin
    destination_label = dest_geo["label"] if dest_geo else destination
    route_label = f"{_short_place(origin_label)} -> {_short_place(destination_label)}"

    drivers = _human_drivers(origin_label, destination_label, weather, is_weekend, distance_km)

    return {
        "route": route_label,
        "slots": slots,
        "recommendation": recommendation,
        "reason": _build_reason(best_idx, slots[best_idx]["stress"], slots),
        "stress_drivers": drivers,
    }
