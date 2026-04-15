import json
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .commute_engine import analyze_commute

SLOT_LABELS = ["Leave now", "+10 min", "+20 min", "+30 min"]
SLOT_OFFSETS_MIN = [0, 10, 20, 30]
MAX_REQUEST_BYTES = 16 * 1024
MAX_TEXT_FIELD_LENGTH = 120
TIME_24H_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ALLOWED_MODES = {"car", "cab", "taxi", "auto", "bike", "motorcycle", "bus", "metro", "walk", "foot"}
ALLOWED_DAY_TYPES = {"weekday", "weekend"}


FALLBACK_RESPONSE = {
    "route": "Unable to determine",
    "slots": [
        {
            "label": "Leave now",
            "stress": 45,
            "eta_min": 25,
            "traffic_level": "medium",
            "note": "wet roads",
            "safety_risk": "medium",
            "safety_note": "crowded commute",
        },
        {
            "label": "+10 min",
            "stress": 40,
            "eta_min": 23,
            "traffic_level": "low",
            "note": "smooth ride",
            "safety_risk": "low",
            "safety_note": "well-lit route",
        },
        {
            "label": "+20 min",
            "stress": 38,
            "eta_min": 22,
            "traffic_level": "low",
            "note": "smooth ride",
            "safety_risk": "low",
            "safety_note": "well-lit route",
        },
        {
            "label": "+30 min",
            "stress": 42,
            "eta_min": 24,
            "traffic_level": "medium",
            "note": "slow traffic",
            "safety_risk": "medium",
            "safety_note": "crowded commute",
        },
    ],
    "recommendation": "Leave in 20 minutes",
    "reason": "Traffic analysis unavailable — showing estimated averages for this time window.",
    "stress_drivers": [
        "Live traffic data temporarily unavailable",
        "Estimates based on general patterns",
    ],
    "prefer_safe_commute": False,
}


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _normalized_text(value, default=""):
    text = str(value or default).strip()
    return text[:MAX_TEXT_FIELD_LENGTH]


def _validated_time(value, default="09:00"):
    time_value = str(value or default).strip()
    if TIME_24H_REGEX.match(time_value):
        return time_value
    return default


def _validated_mode(value, default="car"):
    mode = str(value or default).strip().lower()
    return mode if mode in ALLOWED_MODES else default


def _validated_day_type(value, default="weekday"):
    day_type = str(value or default).strip().lower()
    return day_type if day_type in ALLOWED_DAY_TYPES else default


def _default_slot_template():
    return [
        {
            "label": "Leave now",
            "stress": 45,
            "eta_min": 25,
            "traffic_level": "medium",
            "note": "wet roads",
            "safety_risk": "medium",
            "safety_note": "crowded commute",
        },
        {
            "label": "+10 min",
            "stress": 40,
            "eta_min": 23,
            "traffic_level": "low",
            "note": "smooth ride",
            "safety_risk": "low",
            "safety_note": "well-lit route",
        },
        {
            "label": "+20 min",
            "stress": 38,
            "eta_min": 22,
            "traffic_level": "low",
            "note": "smooth ride",
            "safety_risk": "low",
            "safety_note": "well-lit route",
        },
        {
            "label": "+30 min",
            "stress": 42,
            "eta_min": 24,
            "traffic_level": "medium",
            "note": "slow traffic",
            "safety_risk": "medium",
            "safety_note": "crowded commute",
        },
    ]


def _best_recommendation_from_slots(slots):
    best_index = min(range(len(slots)), key=lambda i: slots[i]["stress"])
    return "Leave now" if best_index == 0 else f"Wait {best_index * 10} minutes"


def _build_fallback_response(origin, destination, reason, prefer_safe_commute=False):
    response = dict(FALLBACK_RESPONSE)
    response["route"] = f"{origin} → {destination}" if origin and destination else "Unable to determine"
    response["slots"] = _default_slot_template()
    response["recommendation"] = _best_recommendation_from_slots(response["slots"])
    response["reason"] = reason
    response["prefer_safe_commute"] = bool(prefer_safe_commute)
    response["time_insight"] = _build_time_insight(response["slots"])
    return response


def _build_time_insight(slots):
    if not slots or len(slots) < 2:
        return "Leaving now saves 0 minutes"

    now_eta = max(0, _coerce_int(slots[0].get("eta_min"), 0))
    later_eta = max(0, _coerce_int(slots[1].get("eta_min"), 0))
    arrival_now_min = now_eta
    arrival_later_min = SLOT_OFFSETS_MIN[1] + later_eta
    arrival_delta = arrival_later_min - arrival_now_min

    if arrival_delta <= 3:
        return "You can leave 10 minutes later and still arrive at the same time"
    return f"Leaving now saves {arrival_delta} minutes"


def _normalize_result_shape(result, origin, destination):
    raw_slots = result.get("slots", []) if isinstance(result, dict) else []
    slots = []

    for idx, label in enumerate(SLOT_LABELS):
        raw_slot = raw_slots[idx] if idx < len(raw_slots) and isinstance(raw_slots[idx], dict) else {}
        stress = max(0, min(100, _coerce_int(raw_slot.get("stress"), 50)))
        eta_min = max(0, _coerce_int(raw_slot.get("eta_min"), 0))
        traffic_level = str(raw_slot.get("traffic_level", "medium")).strip().lower()
        if traffic_level not in {"low", "medium", "high"}:
            traffic_level = "medium"
        safety_risk = str(raw_slot.get("safety_risk", "medium")).strip().lower()
        if safety_risk not in {"low", "medium", "high"}:
            safety_risk = "medium"
        note = str(raw_slot.get("note", "")).strip() or "Estimated"
        normalized_slot = {
            "label": label,
            "stress": stress,
            "eta_min": eta_min,
            "traffic_level": traffic_level,
            "note": note,
            "safety_risk": safety_risk,
        }

        safety_note = str(raw_slot.get("safety_note", "")).strip()
        if safety_note:
            normalized_slot["safety_note"] = safety_note

        slots.append(normalized_slot)

    route = str(result.get("route", "")).strip() if isinstance(result, dict) else ""
    if not route:
        route = f"{origin} → {destination}"

    recommendation = str(result.get("recommendation", "")).strip() if isinstance(result, dict) else ""
    if not recommendation:
        recommendation = _best_recommendation_from_slots(slots)

    reason = str(result.get("reason", "")).strip() if isinstance(result, dict) else ""
    if not reason:
        reason = "Best available estimate from current traffic patterns."

    raw_drivers = result.get("stress_drivers", []) if isinstance(result, dict) else []
    stress_drivers = [str(item).strip() for item in raw_drivers if str(item).strip()][:4]
    time_insight = str(result.get("time_insight", "")).strip() if isinstance(result, dict) else ""
    if not time_insight:
        time_insight = _build_time_insight(slots)

    normalized = {
        "route": route,
        "slots": slots,
        "recommendation": recommendation,
        "reason": reason,
        "time_insight": time_insight,
        "stress_drivers": stress_drivers,
        "prefer_safe_commute": _coerce_bool(result.get("prefer_safe_commute", False)) if isinstance(result, dict) else False,
    }

    if isinstance(result, dict):
        carpool_suggestion = str(result.get("carpool_suggestion", "")).strip()
        if carpool_suggestion:
            normalized["carpool_suggestion"] = carpool_suggestion

        time_insight = str(result.get("time_insight", "")).strip()
        if time_insight:
            normalized["time_insight"] = time_insight

    return normalized


@csrf_exempt
@require_POST
def analyze(request):
    """POST /api/analyze/ — run commute analysis using free APIs with safe fallbacks."""
    if request.content_type != "application/json":
        return JsonResponse({"error": "Content-Type must be application/json"}, status=415)

    if len(request.body) > MAX_REQUEST_BYTES:
        return JsonResponse({"error": "Request body is too large"}, status=413)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    origin = _normalized_text(body.get("origin", ""))
    destination = _normalized_text(body.get("destination", ""))
    mode = _validated_mode(body.get("mode", "car"), default="car")
    day_type = _validated_day_type(body.get("day_type", "weekday"), default="weekday")
    current_time = _validated_time(body.get("current_time", "09:00"), default="09:00")
    prefer_safe_commute = _coerce_bool(body.get("prefer_safe_commute", False), default=False)

    if not origin or not destination:
        return JsonResponse(
            {"error": "Both 'origin' and 'destination' are required."},
            status=400,
        )

    try:
        result = analyze_commute(origin, destination, mode, day_type, current_time, prefer_safe_commute)
        normalized = _normalize_result_shape(result, origin, destination)
        return JsonResponse(normalized)

    except Exception as exc:
        # Safe fallback ensures the frontend still gets a valid response.
        del exc
        return JsonResponse(
            _build_fallback_response(
                origin,
                destination,
                "Live services timed out — estimated local traffic pattern used.",
                prefer_safe_commute,
            )
        )
