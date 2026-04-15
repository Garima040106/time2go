// Utility functions for Time2Go app

export const DEMO_SCENARIOS = {
  'koramangala-whitefield': {
    form: {
      origin: 'Koramangala, Bengaluru',
      destination: 'Whitefield, Bengaluru',
      mode: 'auto',
      day_type: 'weekday',
      current_time: '08:45',
      prefer_safe_commute: false
    },
    result: {
      route: 'Koramangala → Whitefield',
      recommendation: 'Leave in 30 minutes',
      reason: 'A short wait skips peak signal stacking near ORR merge points.',
      time_insight: 'Leaving now saves 7 minutes',
      slots: [
        { label: 'Leave now', stress: 82, eta_min: 42, note: 'Rush bottlenecks' },
        { label: '+10 min', stress: 77, eta_min: 39, note: 'Still heavy' },
        { label: '+20 min', stress: 72, eta_min: 37, note: 'Flow improving' },
        { label: '+30 min', stress: 66, eta_min: 35, note: 'Best window' }
      ],
      stress_drivers: [
        'Office commute clusters around intermediate junctions',
        'Long corridor amplifies every red-light delay'
      ]
    }
  },
  'jayanagar-hebbal': {
    form: {
      origin: 'Jayanagar 4th Block, Bengaluru',
      destination: 'Hebbal Flyover, Bengaluru',
      mode: 'motorcycle',
      day_type: 'weekday',
      current_time: '18:10',
      prefer_safe_commute: true
    },
    result: {
      route: 'Jayanagar → Hebbal Flyover',
      recommendation: 'Leave now',
      reason: 'Current slot beats the post-6:20 merge surge toward northern corridors.',
      time_insight: 'You can leave 10 minutes later and still arrive at the same time',
      slots: [
        { label: 'Leave now', stress: 61, eta_min: 39, note: 'Moving tight; safer commute option' },
        { label: '+10 min', stress: 67, eta_min: 42, note: 'Evening peak; safer commute option' },
        { label: '+20 min', stress: 74, eta_min: 46, note: 'Signal queues; safer commute option' },
        { label: '+30 min', stress: 71, eta_min: 44, note: 'Crowded exits; safer commute option' }
      ],
      stress_drivers: [
        'Evening outbound wave builds quickly after 6 PM',
        'Flyover entry lanes get dense during peak merging'
      ]
    }
  },
  'indiranagar-airport': {
    form: {
      origin: 'Indiranagar, Bengaluru',
      destination: 'Kempegowda International Airport, Bengaluru',
      mode: 'car',
      day_type: 'weekend',
      current_time: '13:40',
      prefer_safe_commute: false
    },
    result: {
      route: 'Indiranagar → Bengaluru Airport',
      recommendation: 'Leave in 20 minutes',
      reason: 'A brief delay lands in a cleaner runway before afternoon leisure traffic thickens again.',
      time_insight: 'Leaving now saves 4 minutes',
      slots: [
        { label: 'Leave now', stress: 57, eta_min: 53, note: 'Steady flow' },
        { label: '+10 min', stress: 52, eta_min: 50, note: 'Smoother lanes' },
        { label: '+20 min', stress: 48, eta_min: 48, note: 'Calmest run' },
        { label: '+30 min', stress: 55, eta_min: 51, note: 'Leisure rebound' }
      ],
      stress_drivers: [
        'Weekend trip traffic pulses around airport access roads',
        'Long express corridor rewards timing the cleaner slot'
      ]
    }
  }
};

export function stressColor(stress) {
  if (stress < 40) return '#0d9488';
  if (stress < 65) return '#ea580c';
  return '#dc2626';
}

export function stressBand(stress) {
  if (stress < 40) return 'Low stress';
  if (stress < 65) return 'Moderate stress';
  return 'High stress';
}

export function toInt(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.round(n) : fallback;
}

export function safeString(value, fallback = '') {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function getApiBaseUrl() {
  const fromEnv = safeString(process.env.REACT_APP_API_BASE_URL);
  if (fromEnv) {
    return fromEnv.replace(/\/$/, '');
  }

  const isLocalhost =
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

  // In CRA dev mode, point API calls to Django directly.
  return isLocalhost ? 'http://127.0.0.1:8000' : '';
}

export async function fetchAnalyze(payload, timeoutMs = 4500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const apiBase = getApiBaseUrl();
  const apiUrl = `${apiBase}/api/analyze/`;
  
  try {
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    let result = {};
    try {
      result = await response.json();
    } catch (_) {
      result = {};
    }

    if (!response.ok) {
      throw new Error(result.error || 'Server error');
    }

    return result;
  } finally {
    clearTimeout(timer);
  }
}

export function generateSimulatedFallback(origin, destination, preferSafeCommute) {
  const saferNote = preferSafeCommute ? 'safer commute option' : '';
  const mergeNote = (base) => saferNote ? `${base}; ${saferNote}` : base;

  return {
    route: `${origin} → ${destination}`,
    recommendation: 'Leave in 20 minutes',
    reason: 'Backend is resting; showing a quick local estimate so you can still decide.',
    time_insight: 'Leaving now saves 3 minutes',
    slots: [
      { label: 'Leave now', stress: preferSafeCommute ? 61 : 64, eta_min: 36, note: mergeNote('Signals stacking') },
      { label: '+10 min', stress: preferSafeCommute ? 55 : 58, eta_min: 34, note: mergeNote('Flow stabilizing') },
      { label: '+20 min', stress: preferSafeCommute ? 49 : 52, eta_min: 32, note: mergeNote('Best gap window') },
      { label: '+30 min', stress: preferSafeCommute ? 54 : 57, eta_min: 33, note: mergeNote('Back to busy') }
    ],
    stress_drivers: [
      'Short-term estimate built from typical peak-hour patterns',
      'Try again shortly for live route and weather signals'
    ],
    prefer_safe_commute: !!preferSafeCommute
  };
}

export function normalizeResult(payload, origin, destination) {
  const labels = ['Leave now', '+10 min', '+20 min', '+30 min'];
  const rawSlots = Array.isArray(payload?.slots) ? payload.slots : [];

  const slots = labels.map((label, idx) => {
    const src = rawSlots[idx] || {};
    const stress = Math.max(0, Math.min(100, toInt(src.stress, 55)));
    const eta = Math.max(1, toInt(src.eta_min, 30));
    const note = safeString(src.note, 'Estimated');
    const safetyRisk = safeString(src.safety_risk, '');
    const safetyNote = safeString(src.safety_note, '');
    return {
      label: safeString(src.label, label),
      stress,
      eta_min: eta,
      note,
      band: stressBand(stress),
      safety_risk: safetyRisk,
      safety_note: safetyNote,
    };
  });

  const slotsWithLiveNotes = slots.map((slot, idx) => {
    const prev = idx > 0 ? slots[idx - 1] : null;
    const next = idx < slots.length - 1 ? slots[idx + 1] : null;
    let livePhrase = 'signals clearing';

    if (prev) {
      const delta = slot.stress - prev.stress;
      if (delta >= 3) {
        livePhrase = 'rush building';
      } else if (delta <= -3) {
        livePhrase = 'traffic easing';
      } else {
        livePhrase = next && next.stress <= slot.stress - 3 ? 'signals clearing' : 'traffic easing';
      }
    } else if (next && next.stress >= slot.stress + 3) {
      livePhrase = 'rush building';
    }

    return {
      ...slot,
      live_note: `${slot.note} · ${livePhrase}`
    };
  });

  let timeInsight = safeString(payload?.time_insight);
  if (!timeInsight) {
    const nowArrival = slotsWithLiveNotes[0].eta_min;
    const laterArrival = 10 + slotsWithLiveNotes[1].eta_min;
    const arrivalDelta = laterArrival - nowArrival;
    timeInsight = arrivalDelta <= 3
      ? 'You can leave 10 minutes later and still arrive at the same time'
      : `Leaving now saves ${arrivalDelta} minutes`;
  }

  const recommendation = safeString(payload?.recommendation, 'Leave now');
  const reason = safeString(payload?.reason, 'Using best available traffic estimate.');

  const stressDrivers = Array.isArray(payload?.stress_drivers)
    ? payload.stress_drivers
        .map(item => safeString(item))
        .filter(Boolean)
        .slice(0, 4)
    : [];

  // Get safety_risk from best (lowest stress) slot
  let safetyRisk = '';
  if (slotsWithLiveNotes.length > 0) {
    const bestIdx = slotsWithLiveNotes.reduce((minIdx, slot, idx) => 
      slot.stress < slotsWithLiveNotes[minIdx].stress ? idx : minIdx
    , 0);
    safetyRisk = slotsWithLiveNotes[bestIdx].safety_risk;
  }

  return {
    route: safeString(payload?.route, `${origin} → ${destination}`),
    recommendation,
    reason,
    time_insight: timeInsight,
    slots: slotsWithLiveNotes,
    stress_drivers: stressDrivers,
    prefer_safe_commute: !!payload?.prefer_safe_commute,
    safety_risk: safetyRisk,
  };
}
