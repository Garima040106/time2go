# Time2Go

Tiny Django backend + frontend app for commute departure suggestions.

## What this setup includes

- One frontend page at `/` (served from `index.html` with the existing layout).
- One backend endpoint: `POST /api/analyze/`.
- Real-data commute pipeline using free services where available:
	- Geocoding: OpenStreetMap Nominatim
	- Routing: OSRM public API
	- Weather: Open-Meteo hourly forecast
- No database usage in app logic.
- No auth.
- CORS enabled (`CORS_ALLOW_ALL_ORIGINS=True`) for local frontend/backend flexibility.
- Smart fallback heuristics if any external API is unavailable or slow.

## Request payload

`POST /api/analyze/`

```json
{
	"origin": "Koramangala, Bengaluru",
	"destination": "Whitefield, Bengaluru",
	"mode": "bike",
	"day_type": "weekday",
	"current_time": "08:45"
}
```

## Response shape

```json
{
	"route": "",
	"slots": [
		{"label": "Leave now", "stress": 0, "eta_min": 0, "note": ""},
		{"label": "+10 min", "stress": 0, "eta_min": 0, "note": ""},
		{"label": "+20 min", "stress": 0, "eta_min": 0, "note": ""},
		{"label": "+30 min", "stress": 0, "eta_min": 0, "note": ""}
	],
	"recommendation": "",
	"reason": "",
	"stress_drivers": []
}
```

## Run locally

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Optional env in `.env`:

No API key is required for the default pipeline.

3. Start server:

```bash
python manage.py runserver
```

4. Open:

`http://127.0.0.1:8000/`