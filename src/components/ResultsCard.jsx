import React from 'react';

export default function ResultsCard({ recommendation, reason, timeInsight, route }) {
  return (
    <div className="rec-card">
      <div className="rec-label">Recommended Option</div>
      <div className="rec-action">{recommendation}</div>
      <div className="rec-reason">{reason}</div>
      {timeInsight && <div className="rec-insight">{timeInsight}</div>}
      {route && (
        <div className="route-line">
          <strong>Route:</strong> {route}
        </div>
      )}
    </div>
  );
}
