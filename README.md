# Time2Go

Time2Go is a stress-aware commute planner that recommends the best departure slot across the next 30 minutes.

It combines route context, time-window traffic behavior, weather impact, and safety-aware preferences to return practical advice in seconds.

## Why this project matters

- Commute decisions are usually guesswork.
- Existing map ETAs do not always answer: "Should I leave now or wait 10-20 minutes?"
- Time2Go focuses on decision quality, not only route calculation.

## What Time2Go does

- Scores 4 departure slots: `Leave now`, `+10 min`, `+20 min`, `+30 min`
- Predicts stress, ETA, traffic level, and safety signals per slot
- Generates a human-friendly recommendation and reason
- Supports safety-aware commute preference (`prefer_safe_commute`)
- Adds optional carpool and timing insights where relevant
- Uses deterministic fallbacks when external data is slow/unavailable

## Tech stack

- Backend: Django 6 (`api/commute_engine.py`, `api/views.py`)
- Frontend: React 18 (`src/`)
- Data sources (optional):
	- OpenStreetMap Nominatim (geocoding)
	- OSRM (route signal)
	- Open-Meteo (weather)

No paid API key is required.

## Architecture at a glance

1. Frontend posts route + context to `POST /api/analyze/`
2. Backend validates and normalizes request
3. Commute engine computes slot-level scoring
4. Response returns normalized shape with resilient fallback guarantees

## API contract

Endpoint:

`POST /api/analyze/`

### Request example

```json
{
	"origin": "Koramangala, Bengaluru",
	"destination": "Whitefield, Bengaluru",
	"mode": "car",
	"day_type": "weekday",
	"current_time": "08:45",
	"prefer_safe_commute": true
}
```

### Response example

```json
{
	"route": "Koramangala -> Whitefield",
	"slots": [
		{
			"label": "Leave now",
			"stress": 72,
			"eta_min": 39,
			"traffic_level": "high",
			"note": "wet roads; crowded commute",
			"safety_risk": "medium",
			"safety_note": "crowded commute"
		},
		{
			"label": "+10 min",
			"stress": 61,
			"eta_min": 35,
			"traffic_level": "medium",
			"note": "smooth ride; safer commute option",
			"safety_risk": "low",
			"safety_note": "well-lit route"
		}
	],
	"recommendation": "Wait 10 minutes",
	"reason": "A brief wait should noticeably reduce traffic stress on this route.",
	"stress_drivers": [
		"Traffic level blended with live route-speed signal",
		"ORR tech corridor rush is slowing this stretch"
	],
	"time_insight": "Waiting 10 minutes is likely to keep arrival time nearly unchanged.",
	"prefer_safe_commute": true,
	"carpool_suggestion": "High chance of shared rides on this route"
}
```

### Notes

- Core fields always present: `route`, `slots`, `recommendation`, `reason`, `stress_drivers`
- Slot fields always normalized: `label`, `stress`, `eta_min`, `traffic_level`, `note`, `safety_risk`
- Optional enrichments: `safety_note`, `time_insight`, `carpool_suggestion`

## Local setup

### 1. Backend setup (Django)

Install dependencies:

```bash
pip install -r requirements.txt
```

Run server:

```bash
python manage.py runserver
```

Backend URL:

`http://127.0.0.1:8000/`

### 2. Frontend setup (React)

Install dependencies:

```bash
npm install
```

Run dev server:

```bash
npm start
```

Frontend URL:

`http://127.0.0.1:3000/`

Production build:

```bash
npm run build
```

## Environment variables

Create a `.env` in project root (optional).

### Engine behavior

```bash
# Enable lightweight live route probe via Nominatim + OSRM
TIME2GO_USE_ROUTE_API=1
```

### Django security/config

```bash
DJANGO_SECRET_KEY=replace-in-production
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# CORS/CSRF
DJANGO_CORS_ALLOW_ALL_ORIGINS=True
DJANGO_CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000

# Production-only knobs
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_HSTS_SECONDS=31536000
```

## Security improvements included

- Env-driven Django secret/debug/allowed-hosts
- CORS and CSRF trusted-origin controls
- Hardened response/clickjacking/referrer settings
- Production HTTPS/HSTS/cookie secure options
- API request hardening:
	- Content-Type enforcement (`application/json`)
	- Request body size limit
	- Input normalization and strict field validation

## Validation and quality checks

Backend tests:

```bash
python manage.py test
```

Frontend build check:

```bash
npm run build
```

Current status in this repo:

- Backend tests passing
- Frontend production build passing

## Project structure

```text
api/                  # Commute scoring engine + API views
time2go_backend/      # Django project settings and URL wiring
src/                  # React app UI components and utilities
public/               # React static template
```

## Hackathon pitch (one-liner)

Time2Go turns raw commute uncertainty into a clear action: leave now or wait for a lower-stress window.