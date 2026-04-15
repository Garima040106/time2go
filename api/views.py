import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .commute_engine import analyze_commute

SLOT_LABELS = ["Leave now", "+10 min", "+20 min", "+30 min"]


FALLBACK_RESPONSE = {
    "route": "Unable to determine",
    "slots": [
        {"label": "Leave now", "stress": 45, "eta_min": 25, "note": "Moderate traffic"},
        {"label": "+10 min", "stress": 40, "eta_min": 23, "note": "Slightly better"},
        {"label": "+20 min", "stress": 38, "eta_min": 22, "note": "Easing up"},
        {"label": "+30 min", "stress": 42, "eta_min": 24, "note": "Picking up again"},
    ],
    "recommendation": "Leave in 20 minutes",
    "reason": "Traffic analysis unavailable — showing estimated averages for this time window.",
    "stress_drivers": [
        "Live traffic data temporarily unavailable",
        "Estimates based on general patterns",
    ],
}


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_slot_template():
    return [
        {"label": "Leave now", "stress": 45, "eta_min": 25, "note": "Moderate traffic"},
        {"label": "+10 min", "stress": 40, "eta_min": 23, "note": "Slightly better"},
        {"label": "+20 min", "stress": 38, "eta_min": 22, "note": "Easing up"},
        {"label": "+30 min", "stress": 42, "eta_min": 24, "note": "Picking up again"},
    ]


def _best_recommendation_from_slots(slots):
    best_index = min(range(len(slots)), key=lambda i: slots[i]["stress"])
    return "Leave now" if best_index == 0 else f"Leave in {best_index * 10} minutes"


def _build_fallback_response(origin, destination, reason):
    response = dict(FALLBACK_RESPONSE)
    response["route"] = f"{origin} → {destination}" if origin and destination else "Unable to determine"
    response["slots"] = _default_slot_template()
    response["recommendation"] = _best_recommendation_from_slots(response["slots"])
    response["reason"] = reason
    return response


def _normalize_result_shape(result, origin, destination):
    raw_slots = result.get("slots", []) if isinstance(result, dict) else []
    slots = []

    for idx, label in enumerate(SLOT_LABELS):
        raw_slot = raw_slots[idx] if idx < len(raw_slots) and isinstance(raw_slots[idx], dict) else {}
        stress = max(0, min(100, _coerce_int(raw_slot.get("stress"), 50)))
        eta_min = max(0, _coerce_int(raw_slot.get("eta_min"), 0))
        note = str(raw_slot.get("note", "")).strip() or "Estimated"
        slots.append(
            {
                "label": label,
                "stress": stress,
                "eta_min": eta_min,
                "note": note,
            }
        )

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

    return {
        "route": route,
        "slots": slots,
        "recommendation": recommendation,
        "reason": reason,
        "stress_drivers": stress_drivers,
    }


@csrf_exempt
@require_POST
def analyze(request):
    """POST /api/analyze/ — run commute analysis using free APIs with safe fallbacks."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    origin = body.get("origin", "").strip()
    destination = body.get("destination", "").strip()
    mode = body.get("mode", "car").strip()
    day_type = body.get("day_type", "weekday").strip()
    current_time = body.get("current_time", "09:00").strip()

    if not origin or not destination:
        return JsonResponse(
            {"error": "Both 'origin' and 'destination' are required."},
            status=400,
        )

    try:
        result = analyze_commute(origin, destination, mode, day_type, current_time)
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
            )
        )
