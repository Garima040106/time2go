import React from 'react';

export default function ResultsCard({
  recommendation,
  reason,
  timeInsight,
  route,
  safetyNote,
  carpoolSuggestion,
  preferSafeCommute,
}) {
  const normalizedSafety = String(safetyNote || '').toLowerCase();
  const isLateWindow = normalizedSafety.includes('late hour');
  const hasCarpool = Boolean(carpoolSuggestion);
  const womenDriverLine = isLateWindow ? 'Women drivers: Limited now' : 'Women drivers: Likely available';
  const womenCarpoolLine = hasCarpool ? 'Women carpooling: Likely available' : 'Women carpooling: Limited now';
  const womenTimingLine = isLateWindow ? 'Night commute: Outside hours' : 'Night commute: Not active';

  return (
    <div className="rec-card">
      <div className="rec-label">Recommended Option</div>
      <div className="rec-action">{recommendation}</div>
      <div className="rec-reason">{reason}</div>
      {timeInsight && <div className="rec-insight">{timeInsight}</div>}
      {(safetyNote || carpoolSuggestion) && (
        <div className="rec-hints">
          {safetyNote && <div className="rec-hint">Safety: {safetyNote}</div>}
          {carpoolSuggestion && <div className="rec-hint">{carpoolSuggestion}</div>}
        </div>
      )}
      {preferSafeCommute && (
        <div className="rec-women-details">
          <div className="rec-women-line">Women-friendly: Enabled</div>
          <div className="rec-women-line">{womenDriverLine}</div>
          <div className="rec-women-line">{womenCarpoolLine}</div>
          <div className="rec-women-line">{womenTimingLine}</div>
        </div>
      )}
      {route && (
        <div className="route-line">
          <strong>Route:</strong> {route}
        </div>
      )}
    </div>
  );
}
