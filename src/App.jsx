import React, { useState } from 'react';
import InputForm from './components/InputForm';
import ResultsCard from './components/ResultsCard';
import StressSlots from './components/StressSlots';
import InsightSection from './components/InsightSection';
import { normalizeResult, fetchAnalyze } from './utils';
import './styles.css';

export default function App() {
  // Form state
  const [origin, setOrigin] = useState('');
  const [destination, setDestination] = useState('');
  const [mode, setMode] = useState('auto');
  const [dayType, setDayType] = useState('weekday');
  const [currentTime, setCurrentTime] = useState('09:00');
  const [preferSafeCommute, setPreferSafeCommute] = useState(false);

  // Result state
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleAnalyze = async () => {
    if (!origin.trim() || !destination.trim()) {
      setError('Please enter both origin and destination');
      return;
    }

    setLoading(true);
    setError('');
    setResults(null);

    try {
      const payload = {
        origin,
        destination,
        mode,
        day_type: dayType,
        current_time: currentTime,
        prefer_safe_commute: preferSafeCommute,
      };

      const data = await fetchAnalyze(payload);
      const normalized = normalizeResult(data, origin, destination);
      setResults(normalized);
    } catch (err) {
      setError(err.message || 'Unable to analyze commute. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleLoadDemo = (scenario) => {
    // scenario is { form: {...}, result: {...} }
    const form = scenario.form || {};
    setOrigin(form.origin || '');
    setDestination(form.destination || '');
    setMode(form.mode || 'auto');
    setDayType(form.day_type || 'weekday');
    setCurrentTime(form.current_time || '09:00');
    setPreferSafeCommute(!!form.prefer_safe_commute);
    setResults(null);
    setError('');
  };

  return (
    <div className="app-container">
      <div className="app">
        {/* Header */}
        <div className="app-header">
          <h1 className="logo">
            Time<span>2</span>Go
          </h1>
          <p className="tagline">Commute intelligence for calmer arrivals.</p>
        </div>

        {/* Error Message */}
        {error && (
          <div className={`error-msg ${error.includes('Unable') ? 'show warning' : 'show'}`}>
            {error}
          </div>
        )}

        {/* Loading Spinner */}
        {loading && (
          <div className="loading show">
            <div className="spinner" />
            <p>Finding the most reliable route for this departure window...</p>
          </div>
        )}

        {/* Input Form */}
        {!results && (
          <>
            <InputForm
              origin={origin}
              destination={destination}
              mode={mode}
              dayType={dayType}
              currentTime={currentTime}
              preferSafeCommute={preferSafeCommute}
              loading={loading}
              onOriginChange={setOrigin}
              onDestinationChange={setDestination}
              onModeChange={setMode}
              onDayTypeChange={setDayType}
              onTimeChange={setCurrentTime}
              onPreferSafeChange={setPreferSafeCommute}
              onAnalyze={handleAnalyze}
              onLoadDemo={handleLoadDemo}
            />

            {!loading && !error && (
              <div className="empty-state">
                <h3>No analysis yet</h3>
                <p>Enter your route details to get a stress-aware recommendation in seconds.</p>
              </div>
            )}
          </>
        )}

        {/* Results */}
        {results && !loading && (
          <div className="results show">
            <ResultsCard
              recommendation={results.recommendation}
              reason={results.reason}
              timeInsight={results.time_insight}
              route={results.route}
              safetyNote={results.safety_note}
              carpoolSuggestion={results.carpool_suggestion}
              preferSafeCommute={results.prefer_safe_commute}
            />

            <StressSlots slots={results.slots} />

            <InsightSection drivers={results.stress_drivers} />

            <button className="btn-demo" onClick={() => setResults(null)}>
              ← New Analysis
            </button>
          </div>
        )}

        {/* Footer */}
        <footer className="footer">
          <span>Time2Go</span>
          <span>Predictive commute planning</span>
        </footer>
      </div>
    </div>
  );
}
