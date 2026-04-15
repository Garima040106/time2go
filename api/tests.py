import json
from unittest.mock import patch

from django.test import Client, TestCase

from .commute_engine import analyze_commute


class AnalyzeApiTests(TestCase):
	def setUp(self):
		self.client = Client()
		self.url = "/api/analyze/"
		self.payload = {
			"origin": "Koramangala, Bengaluru",
			"destination": "Whitefield, Bengaluru",
			"mode": "car",
			"day_type": "weekday",
			"current_time": "08:45",
		}

	def test_analyze_includes_traffic_level_for_each_slot(self):
		mocked = {
			"route": "Koramangala -> Whitefield",
			"slots": [
				{"label": "Leave now", "stress": 60, "eta_min": 40, "traffic_level": "high", "note": "Rush", "safety_risk": "medium", "safety_note": "crowded commute"},
				{"label": "+10 min", "stress": 55, "eta_min": 37, "traffic_level": "medium", "note": "Busy", "safety_risk": "medium"},
				{"label": "+20 min", "stress": 46, "eta_min": 33, "traffic_level": "low", "note": "Open", "safety_risk": "low", "safety_note": "well-lit route"},
				{"label": "+30 min", "stress": 50, "eta_min": 35, "traffic_level": "medium", "note": "Steady", "safety_risk": "medium"},
			],
			"recommendation": "Leave in 20 minutes",
			"reason": "Avoids congestion",
			"stress_drivers": ["Peak hour"],
		}

		with patch("api.views.analyze_commute", return_value=mocked):
			response = self.client.post(
				self.url,
				data=json.dumps(self.payload),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(len(body["slots"]), 4)
		for slot in body["slots"]:
			self.assertIn(slot["traffic_level"], {"low", "medium", "high"})
			self.assertIn(slot["safety_risk"], {"low", "medium", "high"})

	def test_analyze_fallback_has_traffic_level(self):
		with patch("api.views.analyze_commute", side_effect=RuntimeError("timeout")):
			response = self.client.post(
				self.url,
				data=json.dumps(self.payload),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(len(body["slots"]), 4)
		for slot in body["slots"]:
			self.assertIn("traffic_level", slot)
			self.assertIn(slot["traffic_level"], {"low", "medium", "high"})
			self.assertIn("safety_risk", slot)
			self.assertIn(slot["safety_risk"], {"low", "medium", "high"})
			self.assertTrue(slot["note"])

	def test_analyze_accepts_prefer_safe_commute_flag(self):
		payload = dict(self.payload)
		payload["prefer_safe_commute"] = True

		mocked = {
			"route": "Koramangala -> Whitefield",
			"slots": [
				{"label": "Leave now", "stress": 58, "eta_min": 40, "traffic_level": "high", "note": "Rush; safer commute option", "safety_risk": "medium", "safety_note": "crowded commute"},
				{"label": "+10 min", "stress": 53, "eta_min": 37, "traffic_level": "medium", "note": "Busy; safer commute option", "safety_risk": "medium"},
				{"label": "+20 min", "stress": 44, "eta_min": 33, "traffic_level": "low", "note": "Open; safer commute option", "safety_risk": "low", "safety_note": "well-lit route"},
				{"label": "+30 min", "stress": 48, "eta_min": 35, "traffic_level": "medium", "note": "Steady; safer commute option", "safety_risk": "medium"},
			],
			"recommendation": "Wait 20 minutes",
			"reason": "Safer shared route preference applied.",
			"time_insight": "Leaving now saves 7 minutes",
			"stress_drivers": ["Peak hour"],
			"prefer_safe_commute": True,
		}

		with patch("api.views.analyze_commute", return_value=mocked) as mocked_engine:
			response = self.client.post(
				self.url,
				data=json.dumps(payload),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertTrue(body["prefer_safe_commute"])
		self.assertIn("time_insight", body)
		mocked_engine.assert_called_once_with(
			payload["origin"],
			payload["destination"],
			payload["mode"],
			payload["day_type"],
			payload["current_time"],
			True,
		)

	def test_analyze_time_insight_is_single_practical_sentence(self):
		mocked = {
			"route": "Koramangala -> Whitefield",
			"slots": [
				{"label": "Leave now", "stress": 60, "eta_min": 40, "traffic_level": "high", "note": "Rush", "safety_risk": "medium", "safety_note": "crowded commute"},
				{"label": "+10 min", "stress": 56, "eta_min": 32, "traffic_level": "medium", "note": "Busy", "safety_risk": "medium"},
				{"label": "+20 min", "stress": 48, "eta_min": 31, "traffic_level": "low", "note": "Open", "safety_risk": "low", "safety_note": "well-lit route"},
				{"label": "+30 min", "stress": 52, "eta_min": 35, "traffic_level": "medium", "note": "Steady", "safety_risk": "medium"},
			],
			"recommendation": "Wait 20 minutes",
			"reason": "Avoids congestion",
			"stress_drivers": ["Peak hour"],
		}

		with patch("api.views.analyze_commute", return_value=mocked):
			response = self.client.post(
				self.url,
				data=json.dumps(self.payload),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		insight = body.get("time_insight", "")
		self.assertTrue(insight)
		self.assertTrue(
			insight.startswith("You can leave 10 minutes later")
			or insight.startswith("Leaving now saves ")
		)
		self.assertLessEqual(insight.count("."), 1)

	def test_analyze_preserves_carpool_suggestion_when_present(self):
		mocked = {
			"route": "Koramangala -> Whitefield",
			"slots": [
				{"label": "Leave now", "stress": 58, "eta_min": 40, "traffic_level": "high", "note": "Rush; carpool friendly", "safety_risk": "medium", "safety_note": "crowded commute"},
				{"label": "+10 min", "stress": 54, "eta_min": 37, "traffic_level": "medium", "note": "Busy; carpool friendly", "safety_risk": "medium"},
				{"label": "+20 min", "stress": 46, "eta_min": 33, "traffic_level": "low", "note": "Open; carpool friendly", "safety_risk": "low", "safety_note": "well-lit route"},
				{"label": "+30 min", "stress": 50, "eta_min": 35, "traffic_level": "medium", "note": "Steady; carpool friendly", "safety_risk": "medium"},
			],
			"recommendation": "Wait 20 minutes",
			"reason": "Common office corridor is active.",
			"stress_drivers": ["Peak hour"],
			"carpool_suggestion": "High chance of shared rides on this route",
		}

		with patch("api.views.analyze_commute", return_value=mocked):
			response = self.client.post(
				self.url,
				data=json.dumps(self.payload),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(body.get("carpool_suggestion"), "High chance of shared rides on this route")

	def test_analyze_preserves_time_insight_when_present(self):
		mocked = {
			"route": "Koramangala -> Whitefield",
			"slots": [
				{"label": "Leave now", "stress": 58, "eta_min": 40, "traffic_level": "high", "note": "Rush", "safety_risk": "medium"},
				{"label": "+10 min", "stress": 54, "eta_min": 37, "traffic_level": "medium", "note": "Busy", "safety_risk": "medium"},
				{"label": "+20 min", "stress": 46, "eta_min": 33, "traffic_level": "low", "note": "Open", "safety_risk": "low"},
				{"label": "+30 min", "stress": 50, "eta_min": 35, "traffic_level": "medium", "note": "Steady", "safety_risk": "medium"},
			],
			"recommendation": "Wait 20 minutes",
			"reason": "Common office corridor is active.",
			"stress_drivers": ["Peak hour"],
			"time_insight": "Waiting 20 minutes is likely to keep arrival time nearly unchanged.",
		}

		with patch("api.views.analyze_commute", return_value=mocked):
			response = self.client.post(
				self.url,
				data=json.dumps(self.payload),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(
			body.get("time_insight"),
			"Waiting 20 minutes is likely to keep arrival time nearly unchanged.",
		)


class CommuteEngineStressModelTests(TestCase):
	def test_stress_scores_are_deterministic_and_distinct(self):
		result_one = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)
		result_two = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)

		scores_one = [slot["stress"] for slot in result_one["slots"]]
		scores_two = [slot["stress"] for slot in result_two["slots"]]

		self.assertEqual(scores_one, scores_two)
		self.assertEqual(len(scores_one), 4)
		self.assertEqual(len(set(scores_one)), 4)

		for score in scores_one:
			self.assertGreaterEqual(score, 0)
			self.assertLessEqual(score, 100)

		best = min(scores_one)
		next_best = sorted(scores_one)[1]
		self.assertGreaterEqual(next_best - best, 8)

	def test_bike_handles_traffic_better_than_car(self):
		car_result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)
		bike_result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"bike",
			"weekday",
			"08:45",
		)

		car_avg = sum(slot["stress"] for slot in car_result["slots"]) / 4.0
		bike_avg = sum(slot["stress"] for slot in bike_result["slots"]) / 4.0
		self.assertLess(bike_avg, car_avg)

	def test_notes_include_subtle_weather_or_safety_hints(self):
		result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)

		allowed = {
			"wet roads",
			"slow traffic",
			"smooth ride",
			"well-lit route",
			"late hour risk",
			"crowded commute",
			"carpool friendly",
		}
		for slot in result["slots"]:
			note_parts = [part.strip().lower() for part in slot["note"].split(";") if part.strip()]
			for part in note_parts:
				self.assertIn(part, allowed)
				self.assertLessEqual(len(part.split()), 4)

	def test_late_night_safety_risk_can_be_high(self):
		result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"23:10",
		)

		risks = [slot["safety_risk"] for slot in result["slots"]]
		self.assertIn("high", risks)
		for slot in result["slots"]:
			if slot["safety_risk"] == "high":
				self.assertIn("safety_note", slot)
				self.assertEqual(slot["safety_note"], "late hour risk")

	def test_hotspot_routes_raise_stress_and_add_hotspot_driver(self):
		with patch("api.commute_engine._estimate_distance_without_route", return_value=16.0):
			plain = analyze_commute(
				"Koramangala, Bengaluru",
				"MG Road, Bengaluru",
				"car",
				"weekday",
				"08:45",
			)
			hotspot = analyze_commute(
				"Koramangala via Silk Board, Bengaluru",
				"Whitefield via ORR, Bengaluru",
				"car",
				"weekday",
				"08:45",
			)

		plain_avg = sum(slot["stress"] for slot in plain["slots"]) / 4.0
		hotspot_avg = sum(slot["stress"] for slot in hotspot["slots"]) / 4.0
		self.assertGreater(hotspot_avg, plain_avg)

		drivers_text = " ".join(hotspot.get("stress_drivers", []))
		self.assertTrue(
			"Silk Board bottleneck" in drivers_text or "ORR tech corridor rush" in drivers_text
		)

	def test_unknown_locations_use_generic_location_signal(self):
		result = analyze_commute(
			"Maple Street, Sampletown",
			"River Plaza, Sampletown",
			"car",
			"weekday",
			"13:10",
		)

		drivers_text = " ".join(result.get("stress_drivers", []))
		self.assertTrue(
			"Local junction" in drivers_text
			or "Mixed arterial" in drivers_text
			or "Urban corridor" in drivers_text
		)

	def test_recommendation_is_human_and_reason_is_concise(self):
		result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield via ORR, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)

		recommendation = result.get("recommendation", "")
		allowed_starts = (
			"Leave now",
			"Wait ",
			"Delay slightly for smoother ride",
		)
		self.assertTrue(recommendation.startswith(allowed_starts))

		reason = result.get("reason", "").strip()
		self.assertLessEqual(len(reason.split()), 20)

	def test_small_improvement_prefers_leave_now(self):
		slots = [
			{"stress": 52},
			{"stress": 50},
			{"stress": 49},
			{"stress": 48},
		]
		from .commute_engine import _choose_recommendation

		recommendation, reason, _ = _choose_recommendation(slots)
		self.assertEqual(recommendation, "Leave now")
		self.assertLessEqual(len(reason.split()), 20)

	def test_large_improvement_recommends_wait(self):
		slots = [
			{"stress": 70},
			{"stress": 58},
			{"stress": 60},
			{"stress": 64},
		]
		from .commute_engine import _choose_recommendation

		recommendation, reason, _ = _choose_recommendation(slots)
		self.assertEqual(recommendation, "Wait 10 minutes")
		self.assertLessEqual(len(reason.split()), 20)

	def test_same_origin_destination_returns_calm_immediate_output(self):
		result = analyze_commute(
			"MG Road, Bengaluru",
			"MG Road, Bengaluru",
			"car",
			"weekday",
			"09:15",
		)

		self.assertEqual(result["recommendation"], "Leave now")
		self.assertEqual(len(result["slots"]), 4)
		for slot in result["slots"]:
			self.assertLessEqual(slot["stress"], 20)
			self.assertLessEqual(slot["eta_min"], 12)
			self.assertEqual(slot["traffic_level"], "low")

	def test_very_short_distance_prefers_immediate_departure(self):
		with patch("api.commute_engine._estimate_distance_without_route", return_value=1.1):
			result = analyze_commute(
				"1st Main, Bengaluru",
				"2nd Main, Bengaluru",
				"bike",
				"weekday",
				"11:20",
			)

		self.assertEqual(result["recommendation"], "Leave now")
		for slot in result["slots"]:
			self.assertLessEqual(slot["stress"], 20)
			self.assertLessEqual(slot["eta_min"], 12)

	def test_late_night_keeps_stress_low_and_immediate(self):
		result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"23:10",
		)

		self.assertEqual(result["recommendation"], "Leave now")
		for slot in result["slots"]:
			self.assertLessEqual(slot["stress"], 20)
			self.assertLessEqual(slot["eta_min"], 12)

	def test_early_morning_keeps_stress_low_and_immediate(self):
		result = analyze_commute(
			"Jayanagar, Bengaluru",
			"Hebbal, Bengaluru",
			"car",
			"weekday",
			"06:10",
		)

		self.assertEqual(result["recommendation"], "Leave now")
		for slot in result["slots"]:
			self.assertLessEqual(slot["stress"], 20)
			self.assertLessEqual(slot["eta_min"], 12)

	def test_prefer_safe_commute_reduces_stress_and_adds_note(self):
		regular = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"13:10",
		)
		safer = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield, Bengaluru",
			"car",
			"weekday",
			"13:10",
			prefer_safe_commute=True,
		)

		self.assertTrue(safer.get("prefer_safe_commute"))
		regular_avg = sum(slot["stress"] for slot in regular["slots"]) / 4.0
		safer_avg = sum(slot["stress"] for slot in safer["slots"]) / 4.0
		self.assertLess(safer_avg, regular_avg)

		for slot in safer["slots"]:
			self.assertIn("safer commute option", slot["note"].lower())

	def test_carpool_is_suggested_for_peak_office_route(self):
		result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield via ORR, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)

		self.assertEqual(result.get("carpool_suggestion"), "High chance of shared rides on this route")
		for slot in result["slots"]:
			self.assertIn("carpool friendly", slot["note"].lower())

	def test_carpool_not_suggested_off_peak_or_non_office_route(self):
		off_peak = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield via ORR, Bengaluru",
			"car",
			"weekday",
			"13:10",
		)
		non_office = analyze_commute(
			"Maple Street, Sampletown",
			"River Plaza, Sampletown",
			"car",
			"weekday",
			"08:45",
		)

		self.assertNotIn("carpool_suggestion", off_peak)
		self.assertNotIn("carpool_suggestion", non_office)
		for slot in off_peak["slots"] + non_office["slots"]:
			self.assertNotIn("carpool friendly", slot["note"].lower())

	def test_engine_includes_time_insight(self):
		result = analyze_commute(
			"Koramangala, Bengaluru",
			"Whitefield via ORR, Bengaluru",
			"car",
			"weekday",
			"08:45",
		)

		self.assertTrue(result.get("time_insight"))
