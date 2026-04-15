import React from 'react';
import { DEMO_SCENARIOS } from '../utils';

export default function InputForm({
  origin,
  destination,
  mode,
  dayType,
  currentTime,
  preferSafeCommute,
  loading,
  onOriginChange,
  onDestinationChange,
  onModeChange,
  onDayTypeChange,
  onTimeChange,
  onPreferSafeChange,
  onAnalyze,
  onLoadDemo,
}) {
  // Convert DEMO_SCENARIOS object to array
  const demoArray = Object.entries(DEMO_SCENARIOS).map(([key, scenario]) => ({
    title: key
      .split('-')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' '),
    ...scenario,
  }));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onAnalyze();
      }}
    >
      {/* Origin */}
      <div className="form-group">
        <label htmlFor="origin">Origin</label>
        <input
          id="origin"
          type="text"
          placeholder="Starting location"
          value={origin}
          onChange={(e) => onOriginChange(e.target.value)}
          disabled={loading}
        />
      </div>

      {/* Destination */}
      <div className="form-group">
        <label htmlFor="destination">Destination</label>
        <input
          id="destination"
          type="text"
          placeholder="Ending location"
          value={destination}
          onChange={(e) => onDestinationChange(e.target.value)}
          disabled={loading}
        />
      </div>

      {/* Mode and Day Type Row */}
      <div className="row">
        <div className="form-group">
          <label htmlFor="mode">Mode</label>
          <select id="mode" value={mode} onChange={(e) => onModeChange(e.target.value)} disabled={loading}>
            <option value="auto">Auto</option>
            <option value="bus">Bus</option>
            <option value="metro">Metro</option>
            <option value="motorcycle">Motorcycle</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="day-type">Day Type</label>
          <select id="day-type" value={dayType} onChange={(e) => onDayTypeChange(e.target.value)} disabled={loading}>
            <option value="weekday">Weekday</option>
            <option value="weekend">Weekend</option>
          </select>
        </div>
      </div>

      {/* Current Time */}
      <div className="form-group">
        <label htmlFor="departure-time">Departure Time (24h)</label>
        <input
          id="departure-time"
          type="time"
          value={currentTime}
          onChange={(e) => onTimeChange(e.target.value)}
          disabled={loading}
        />
      </div>

      {/* Preference Toggle */}
      <div className="form-group">
        <div className="toggle-group">
          <input
            type="checkbox"
            id="prefer-safe"
            checked={preferSafeCommute}
            onChange={(e) => onPreferSafeChange(e.target.checked)}
            disabled={loading}
          />
          <label htmlFor="prefer-safe">Prefer women-friendly commute</label>
        </div>
        <div className="toggle-hint">Prioritizes bus and metro when enabled.</div>
      </div>

      {/* Analyze Button */}
      <button type="submit" className="btn" disabled={loading}>
        {loading ? (
          <span className="btn-content">
            <span className="btn-spinner" aria-hidden="true" />
            Analyzing route
          </span>
        ) : (
          'Analyze Commute'
        )}
      </button>

      {/* Demo Section */}
      <div className="demo-section">
        <div className="demo-title">Sample Scenarios</div>
        <div className="demo-grid">
          {demoArray.map((scenario, idx) => (
            <button
              key={idx}
              type="button"
              className="demo-chip"
              onClick={() => onLoadDemo(scenario)}
              disabled={loading}
            >
              {scenario.title}
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}
