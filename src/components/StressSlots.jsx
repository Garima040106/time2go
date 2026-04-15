import React, { useEffect, useState } from 'react';
import { stressColor, stressBand } from '../utils';

export default function StressSlots({ slots }) {
  if (!slots || slots.length === 0) {
    return (
      <div className="empty-state compact">
        <h3>No stress slots available</h3>
        <p>Try another departure time to see stress forecasting by time window.</p>
      </div>
    );
  }

  // Find the best (lowest stress) slot
  let bestIndex = 0;
  if (slots.length > 0) {
    bestIndex = slots.reduce((minIdx, slot, idx) =>
      slot.stress < slots[minIdx].stress ? idx : minIdx
    , 0);
  }

  return (
    <>
      <div className="slots-label">Stress Levels</div>
      <div className="stress-scale">
        <div className="scale-item">
          <div className="scale-dot" style={{ backgroundColor: '#0d9488' }} />
          <span>Calm</span>
        </div>
        <div className="scale-item">
          <div className="scale-dot" style={{ backgroundColor: '#ea580c' }} />
          <span>Moderate</span>
        </div>
        <div className="scale-item">
          <div className="scale-dot" style={{ backgroundColor: '#dc2626' }} />
          <span>High</span>
        </div>
      </div>
      <div className="slots">
        {slots.map((slot, idx) => (
          <StressSlot key={idx} slot={slot} isBest={idx === bestIndex} />
        ))}
      </div>
    </>
  );
}

function StressSlot({ slot, isBest }) {
  const [fillWidth, setFillWidth] = useState(0);
  const color = stressColor(slot.stress);
  const band = stressBand(slot.stress);

  useEffect(() => {
    const timer = setTimeout(() => {
      setFillWidth((slot.stress / 10) * 100);
    }, 100);
    return () => clearTimeout(timer);
  }, [slot.stress]);

  return (
    <div className={`slot ${isBest ? 'best' : ''}`} style={{ borderLeftColor: color }}>
      {isBest && <div className="best-badge">Recommended</div>}

      <div className="slot-label">{slot.label}</div>

      <div className="stress-display">
        <div className="stress-number">{slot.stress}</div>
        <div className="stress-band" style={{ color }}>{band}</div>
      </div>

      <div className="slot-bar-container">
        <div className="slot-bar">
          <div
            className="slot-fill"
            style={{
              backgroundColor: color,
              width: `${fillWidth}%`
            }} 
          />
        </div>
      </div>

      <div className="slot-eta">{slot.eta_min} min</div>
      {slot.note && <div className="slot-note">{slot.note}</div>}
    </div>
  );
}
