import React from 'react';

export default function InsightSection({ drivers, safetyRisk }) {
  const hasDrivers = drivers && drivers.length > 0;

  return (
    <div className="drivers-box show">
      <div className="drivers-title">Signals Behind This Recommendation</div>
      {hasDrivers ? (
        drivers.map((driver, idx) => (
          <div key={idx} className="driver-item">
            <span className="driver-dot" />
            <span>{driver}</span>
          </div>
        ))
      ) : (
        <div className="driver-item">
          <span className="driver-dot" />
          <span>Realtime traffic and route reliability were used for this result.</span>
        </div>
      )}
      <div className="risk-note">Safety risk estimate: {safetyRisk || 'N/A'}</div>
    </div>
  );
}
