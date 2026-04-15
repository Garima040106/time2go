# Time2Go

Tiny Django backend + frontend app for commute departure suggestions.

## What this setup includes

- One frontend page at `/` (served from `index.html` with the existing layout).
- One backend endpoint: `POST /api/analyze/`.
- Real-data commute pipeline using free services where available:
	- Default mode: local simulation (no external dependency required)
	- Optional route signal mode: OpenStreetMap Nominatim + OSRM public API
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
		{"label": "Leave now", "stress": 0, "eta_min": 0, "traffic_level": "medium", "note": "", "safety_note": ""},
		{"label": "+10 min", "stress": 0, "eta_min": 0, "traffic_level": "low", "note": "", "safety_note": ""},
		{"label": "+20 min", "stress": 0, "eta_min": 0, "traffic_level": "low", "note": "", "safety_note": ""},
		{"label": "+30 min", "stress": 0, "eta_min": 0, "traffic_level": "high", "note": "", "safety_note": ""}
	],
	"recommendation": "",
	"reason": "",
	"stress_drivers": [],
	"time_insight": "",
	"carpool_suggestion": ""
}
```

Notes:
- Required core fields: recommendation, reason, slots (stress + eta_min + note), stress_drivers.
- Optional enrichments: slot-level safety_note, top-level carpool_suggestion, and time_insight.

## Run locally

### Backend

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Optional env in `.env`:

No API key is required. To enable lightweight live route probing, set:

```bash
TIME2GO_USE_ROUTE_API=1
```

3. Start server:

```bash
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/api/analyze/`.

### Frontend (React)

The frontend is a React 18 app with functional components. To run locally:

1. Install Node dependencies:

```bash
npm install
```

2. Start development server:

```bash
npm start
```

3. The dev server will open at `http://127.0.0.1:3000/`.

The React app makes API requests to `http://127.0.0.1:8000/api/analyze/`. Ensure the backend is running before using the frontend.

**Build for production:**

```bash
npm run build
```

This creates an optimized production build in the `build/` directory.