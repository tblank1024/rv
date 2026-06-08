import React, { useEffect, useState } from "react";
import './debug.css';
import { getServerUrl } from '../utils/api';

console.log("Debug component loaded");

function Debug() {
  const [usbPorts, setUsbPorts] = useState({});
  const [usbConnected, setUsbConnected] = useState(null);
  const [kasaOutlets, setKasaOutlets] = useState({});
  const [kasaConnected, setKasaConnected] = useState(null);
  const [watcherEntries, setWatcherEntries] = useState([]);
  const [watcherErrors, setWatcherErrors] = useState([]);
  const [watcherFile, setWatcherFile] = useState(null);
  const [watcherWhitelist, setWatcherWhitelist] = useState({});
  const [watcherLoading, setWatcherLoading] = useState(false);
  const [watcherMessage, setWatcherMessage] = useState('');
  const [watcherAutoRefresh, setWatcherAutoRefresh] = useState(false);
  const [watcherFilter, setWatcherFilter] = useState('');
  const [synologyStatus, setSynologyStatus] = useState(null);
  const [synologyMessage, setSynologyMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [lastUpdate, setLastUpdate] = useState(null);

  // Fetch USB port status
  const getUsbStatus = async () => {
    console.log('getUsbStatus: Starting request...');
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/usb/status`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      
      console.log('getUsbStatus: Raw response status:', response.status);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log('getUsbStatus: Parsed response:', data);
      
      if (data.success) {
        setUsbPorts(data.ports);
        setUsbConnected(true);
        return data;
      } else {
        setMessage(data.message || 'Failed to fetch USB status');
        setUsbConnected(false);
        return data;
      }
    } catch (error) {
      console.error('Error fetching USB status:', error);
      setMessage('Failed to fetch USB status: ' + error.message);
      setUsbConnected(false);
      return { success: false, message: 'Failed to fetch USB status: ' + error.message };
    }
  };

    // Fetch Kasa outlet status
  const getKasaStatus = async () => {
    console.log('getKasaStatus: Starting request...');
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/kasa/status`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      
      console.log('getKasaStatus: Raw response status:', response.status);
      console.log('getKasaStatus: Raw response ok:', response.ok);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log('getKasaStatus: Parsed response:', data);
      
      if (data.success) {
        console.log('getKasaStatus: Setting outlets:', data.outlets);
        setKasaOutlets(data.outlets);
        setKasaConnected(!Object.values(data.outlets).some(o => o.mock));
        return data;
      } else {
        console.log('getKasaStatus: Response not successful:', data.message);
        setMessage(data.message || 'Failed to fetch Kasa status');
        setKasaConnected(false);
        return data;
      }
    } catch (error) {
      console.error('Error fetching Kasa status:', error);
      setMessage('Failed to fetch Kasa status: ' + error.message);
      setKasaConnected(false);
      return { success: false, message: 'Failed to fetch Kasa status: ' + error.message };
    }
  };

  // Watcher timestamps come either as unix seconds (int) or unix seconds with
  // fractional sub-second precision (string, e.g. "1780931492.2653513").
  const formatWatcherTimestamp = (ts) => {
    const seconds = parseFloat(ts);
    if (Number.isNaN(seconds)) return ts;
    return new Date(seconds * 1000).toLocaleString();
  };

  // Watcher log entries are raw MQTT payloads carrying many bookkeeping fields
  // (dgn, data, instance, ...) beyond the ones the watcher actually tracks.
  // The server ships a {topic: [field_names]} whitelist alongside the log
  // entries (derived from WATCH_SPEC by rv/watcher/watcher.py) so the UI can
  // surface just the fields the watcher cares about without keeping its own
  // copy of WATCH_SPEC in sync.
  const formatWatcherValues = (entry) => {
    const fields = watcherWhitelist[entry.topic] || [];
    const hasTankPct = entry.name === 'TANK_STATUS'
      && 'relative level' in entry && 'resolution' in entry;
    return fields
      .filter((key) => {
        if (hasTankPct && (key === 'relative level' || key === 'resolution')) return false;
        return key in entry;
      })
      .map((key) => `${key}: ${entry[key]}`)
      .concat(hasTankPct
        ? [`level: ${Math.round((entry['relative level'] * 100) / entry['resolution'])}%`]
        : [])
      .join(', ');
  };

  // Fetch watcher MQTT log entries (and any SYS_ERRORS reported within them).
  // `silent` is used by the auto-refresh poll so it can swap in fresh entries
  // without flashing the "Loading..." button state or status message.
  const getWatcherLogs = async (silent = false) => {
    if (!silent) {
      setWatcherLoading(true);
      setWatcherMessage('Loading watcher logs...');
    }
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/watcher/logs?lines=200`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      if (data.success) {
        setWatcherEntries(data.entries);
        setWatcherErrors(data.errors);
        setWatcherFile(data.file);
        setWatcherWhitelist(data.whitelist || {});
        if (!silent) setWatcherMessage(data.message);
      } else if (!silent) {
        setWatcherEntries([]);
        setWatcherErrors([]);
        setWatcherFile(null);
        setWatcherWhitelist({});
        setWatcherMessage(data.message || 'Failed to fetch watcher logs');
      }
    } catch (error) {
      console.error('Error fetching watcher logs:', error);
      if (!silent) setWatcherMessage('Failed to fetch watcher logs: ' + error.message);
    } finally {
      if (!silent) setWatcherLoading(false);
    }
  };

  // Auto-refresh: while enabled, silently re-poll the watcher logs every 4s
  // so the list stays current without the loading-spinner flicker.
  useEffect(() => {
    if (!watcherAutoRefresh) return undefined;
    getWatcherLogs(true);
    const interval = setInterval(() => getWatcherLogs(true), 4000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watcherAutoRefresh]);

  // Control USB port
  const controlUsbPort = async (portNum, action) => {
    try {
      // Optimistic UI update - immediately update the visual state
      setUsbPorts(prevPorts => ({
        ...prevPorts,
        [portNum]: {
          ...prevPorts[portNum],
          enabled: action === 'on'
        }
      }));
      
      const response = await fetch(`${getServerUrl()}/api/debug/usb/${portNum}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action }),
      });
      
      const result = await response.json();
      
      if (result.success) {
        setMessage(result.message);
        // Refresh USB status after a short delay
        setTimeout(getUsbStatus, 500);
      } else {
        setMessage(result.message);
        // If command failed, revert the optimistic update
        setTimeout(getUsbStatus, 100);
      }
    } catch (error) {
      console.error('Error controlling USB port:', error);
      setMessage(`Error controlling USB port ${portNum}`);
      // If network error occurred, revert the optimistic update
      setTimeout(getUsbStatus, 100);
    }
  };

    // Control Kasa outlet
  const controlKasaOutlet = async (outletId, action) => {
    try {
      // Optimistic UI update - immediately update the visual state
      setKasaOutlets(prevOutlets => ({
        ...prevOutlets,
        [outletId]: {
          ...prevOutlets[outletId],
          enabled: action === 'on'
        }
      }));
      
      const response = await fetch(`${getServerUrl()}/api/debug/kasa/${outletId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action }),
      });
      
      const result = await response.json();
      
      if (result.success) {
        setMessage(result.message);
        // Refresh Kasa status after a shorter delay since control already completed
        setTimeout(getKasaStatus, 1000);
      } else {
        setMessage(result.message);
        // If command failed, revert the optimistic update by refreshing immediately
        setTimeout(getKasaStatus, 100);
      }
    } catch (error) {
      console.error('Error controlling Kasa outlet:', error);
      setMessage(`Error controlling Kasa outlet ${outletId}`);
      // If network error occurred, revert the optimistic update
      setTimeout(getKasaStatus, 100);
    }
  };

  // Control Synology NAS
  const controlSynology = async (action) => {
    try {
      console.log(`Sending ${action} command to Synology NAS...`);
      setSynologyMessage(`Sending ${action} command to Synology NAS...`);
      
      // Create an AbortController for timeout handling
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
      
      const response = await fetch(`${getServerUrl()}/api/debug/synology/${action}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      console.log('Synology response status:', response.status);
      console.log('Synology response ok:', response.ok);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      console.log('Synology result:', result);
      
      if (result.success) {
        setSynologyMessage(`${action}: ${result.message}`);
        if (action === 'status' && result.status) {
          console.log('Setting Synology status:', result.status);
          setSynologyStatus(result.status);
        }
      } else {
        setSynologyMessage(`${action} failed: ${result.message}`);
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        console.error('Synology request timed out after 10 seconds');
        setSynologyMessage(`${action} timed out after 10 seconds - check server logs`);
      } else {
        console.error('Error controlling Synology NAS:', error);
        setSynologyMessage(`Error communicating with Synology NAS: ${error.message}`);
      }
    }
  };

    // Initial data load
  useEffect(() => {
    console.log('useEffect: Starting initial data load...');
    const loadData = async () => {
      // Don't set loading to true initially - show page immediately
      setMessage('Loading initial data...');
      try {
        // Load both USB and Kasa status in parallel - timeout is handled in each function
        console.log('useEffect: Calling getUsbStatus and getKasaStatus...');
        await Promise.allSettled([getUsbStatus(), getKasaStatus()]);
        console.log('useEffect: Data loading completed');
        setMessage('Data loaded successfully');
      } catch (error) {
        console.error('Error loading initial data:', error);
        setMessage('Error loading initial data');
      } finally {
        setLastUpdate(new Date());
      }
    };
    
    // Start with the page visible, load data in background
    setLoading(false);
    loadData();
  }, []); // Empty dependency array is correct - we only want this to run once

  // Auto-refresh removed to prevent connection leaks and unwanted updates
  // Power readings will only update when manually controlling outlets

  // Manual refresh function
  const refreshData = async () => {
    setLoading(true);
    setMessage('Refreshing data...');
    await Promise.all([getUsbStatus(), getKasaStatus()]);
    setLoading(false);
    setLastUpdate(new Date());
    setMessage('Data refreshed successfully');
  };

  const commBadge = (connected) => {
    if (connected === null) return null;
    return (
      <span style={{
        marginLeft: '12px', fontSize: '13px', fontWeight: 'normal',
        padding: '2px 8px', borderRadius: '10px',
        backgroundColor: connected ? '#e8f5e9' : '#ffebee',
        color: connected ? '#2e7d32' : '#c62828',
      }}>
        {connected ? 'Connected' : 'Not Connected'}
      </span>
    );
  };

  if (loading) {
    return (
      <div className="debug-container">
        <h1>Debug Control Panel</h1>
        <div className="loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="debug-container">
      <h1>Debug Control Panel</h1>
      
      <div style={{ textAlign: 'center', marginBottom: '20px' }}>
        <button 
          onClick={refreshData}
          disabled={loading}
          style={{
            backgroundColor: '#4CAF50',
            color: 'white',
            padding: '10px 20px',
            border: 'none',
            borderRadius: '5px',
            cursor: loading ? 'not-allowed' : 'pointer',
            fontSize: '16px',
            fontWeight: 'bold'
          }}
        >
          {loading ? 'Refreshing...' : 'Refresh Data'}
        </button>
        {lastUpdate && (
          <div style={{ marginTop: '10px', color: '#666', fontSize: '14px' }}>
            Last updated: {lastUpdate.toLocaleTimeString()}
          </div>
        )}
      </div>
      
      {message && (
        <div className="message-box">
          {message}
        </div>
      )}

      <div className="debug-sections">
        {/* USB Ports Section */}
        <div className="debug-section">
          <h2>Internet Access via USB Port Switch{commBadge(usbConnected)}</h2>
          <div className="control-grid">
            {Object.entries(usbPorts).map(([portNum, portData]) => (
              <div key={portNum} className="control-item">
                <h3>{portData.name}</h3>
                <div className="control-buttons">
                  <label className="radio-control">
                    <input
                      type="radio"
                      name={`usb-${portNum}`}
                      checked={portData.enabled}
                      onChange={() => controlUsbPort(portNum, 'on')}
                    />
                    <span className={`radio-label ${portData.enabled ? 'active' : ''}`}>
                      ON
                    </span>
                  </label>
                  <label className="radio-control">
                    <input
                      type="radio"
                      name={`usb-${portNum}`}
                      checked={!portData.enabled}
                      onChange={() => controlUsbPort(portNum, 'off')}
                    />
                    <span className={`radio-label ${!portData.enabled ? 'active' : ''}`}>
                      OFF
                    </span>
                  </label>
                </div>
                {portData.error && (
                  <div className="error-text">{portData.error}</div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Kasa Power Strip Section */}
        <div className="debug-section">
          <h2>Kasa Power Strip{commBadge(kasaConnected)}</h2>
          <div style={{marginBottom: '10px', fontSize: '12px', color: '#666'}}>
            Debug: kasaOutlets = {JSON.stringify(kasaOutlets, null, 2)}
          </div>
          <div style={{marginBottom: '10px', fontSize: '12px', color: '#666'}}>
            Debug: kasaOutlets has {Object.keys(kasaOutlets).length} entries
          </div>
          <div className="control-grid">
            {Object.entries(kasaOutlets).map(([outletId, outletData]) => {
              const isOffline = outletData.status && ['offline', 'error', 'system_error', 'comm_error'].includes(outletData.status);
              const isMockData = outletData.mock || isOffline;
              
              return (
                <div key={outletId} className={`control-item ${isOffline ? 'offline' : ''}`}>
                  <h3>{outletData.name}</h3>
                  {isMockData && (
                    <div className="status-indicator">
                      {outletData.status === 'offline' && <span className="status-offline">OFFLINE</span>}
                      {outletData.status === 'error' && <span className="status-error">CONNECTION ERROR</span>}
                      {outletData.status === 'system_error' && <span className="status-error">SYSTEM ERROR</span>}
                      {outletData.status === 'comm_error' && <span className="status-error">COMM ERROR</span>}
                      {outletData.mock && !outletData.status && <span className="status-mock">MOCK DATA</span>}
                    </div>
                  )}
                  <div className="control-buttons">
                    <label className="radio-control">
                      <input
                        type="radio"
                        name={`kasa-${outletId}`}
                        checked={outletData.enabled}
                        onChange={() => !isOffline && controlKasaOutlet(outletId, 'on')}
                        disabled={isOffline}
                      />
                      <span className={`radio-label ${outletData.enabled ? 'active' : ''} ${isOffline ? 'disabled' : ''}`}>
                        ON
                      </span>
                    </label>
                    <label className="radio-control">
                      <input
                        type="radio"
                        name={`kasa-${outletId}`}
                        checked={!outletData.enabled}
                        onChange={() => !isOffline && controlKasaOutlet(outletId, 'off')}
                        disabled={isOffline}
                      />
                      <span className={`radio-label ${!outletData.enabled ? 'active' : ''} ${isOffline ? 'disabled' : ''}`}>
                        OFF
                      </span>
                    </label>
                  </div>
                  <div className={`power-display ${isOffline ? 'offline' : ''}`}>
                    Power: {outletData.power_watts}W
                    {isMockData && <span className="mock-indicator"> (simulated)</span>}
                  </div>
                  {outletData.error && (
                    <div className="error-text">{outletData.error}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Synology NAS Section */}
        <div className="debug-section">
          <h2>Synology NAS Control</h2>
          {synologyMessage && (
            <div className="message-box" style={{ marginBottom: '15px' }}>
              {synologyMessage}
            </div>
          )}
          <div className="control-grid">
            <div className="control-item">
              <h3>NAS Power Control</h3>
              <div className="control-buttons">
                <button 
                  className="action-button status-button"
                  onClick={() => controlSynology('status')}
                >
                  Status
                </button>
                <button 
                  className="action-button power-on-button"
                  onClick={() => controlSynology('power-on')}
                >
                  Power On
                </button>
                <button 
                  className="action-button standby-button"
                  onClick={() => controlSynology('standby')}
                >
                  Standby
                </button>
                <button 
                  className="action-button power-off-button"
                  onClick={() => controlSynology('power-off')}
                >
                  Power Off
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Watcher MQTT Logs Section */}
        <div className="debug-section">
          <h2>Watcher MQTT Logs</h2>
          <div style={{ marginBottom: '15px' }}>
            <button
              className="action-button"
              onClick={() => { getWatcherLogs(); setWatcherAutoRefresh(true); }}
              disabled={watcherLoading}
              style={{
                backgroundColor: '#4CAF50',
                color: 'white',
                padding: '10px 20px',
                border: 'none',
                borderRadius: '5px',
                cursor: watcherLoading ? 'not-allowed' : 'pointer',
                fontSize: '16px',
                fontWeight: 'bold'
              }}
            >
              {watcherLoading ? 'Loading...' : 'Show Logs'}
            </button>
            <label
              style={{
                marginLeft: '15px',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '14px',
                color: '#444'
              }}
            >
              <input
                type="checkbox"
                checked={watcherAutoRefresh}
                onChange={(e) => setWatcherAutoRefresh(e.target.checked)}
              />
              Auto-refresh {watcherAutoRefresh ? '(running — every 4s)' : '(paused)'}
            </label>
            {watcherFile && (
              <span style={{ marginLeft: '15px', color: '#666', fontSize: '14px' }}>
                Source: {watcherFile}
              </span>
            )}
          </div>
          {watcherEntries.length > 0 && (
            <div style={{ marginBottom: '10px' }}>
              <input
                type="text"
                placeholder="Filter logs…"
                value={watcherFilter}
                onChange={(e) => setWatcherFilter(e.target.value)}
                style={{
                  width: '100%', boxSizing: 'border-box',
                  padding: '6px 10px', fontSize: '14px',
                  border: '1px solid #ccc', borderRadius: '4px',
                }}
              />
            </div>
          )}

          {watcherMessage && (
            <div className="message-box" style={{ marginBottom: '15px' }}>
              {watcherMessage}
            </div>
          )}

          {watcherErrors.length > 0 && (
            <div style={{ marginBottom: '15px' }}>
              <h3>Triggered Errors ({watcherErrors.length})</h3>
              <div className="log-viewer log-viewer-errors">
                {watcherErrors.slice().reverse().map((entry, idx) => (
                  <div key={idx} className="log-entry log-entry-error">
                    {formatWatcherTimestamp(entry.timestamp)} &mdash; {entry.error}
                  </div>
                ))}
              </div>
            </div>
          )}

          {watcherEntries.length > 0 && (() => {
            const needle = watcherFilter.toLowerCase();
            const filtered = watcherEntries.filter(entry => {
              if (!needle) return true;
              const text = [
                formatWatcherTimestamp(entry.timestamp),
                entry.topic || entry.name,
                entry.name === 'SYS_ERRORS' ? entry.error : formatWatcherValues(entry),
              ].join(' ').toLowerCase();
              return text.includes(needle);
            });
            return (
              <div>
                <h3>
                  Recent MQTT Messages ({filtered.length}{watcherFilter ? ` of ${watcherEntries.length}` : ''})
                </h3>
                <div className="log-viewer">
                  {filtered.slice().reverse().map((entry, idx) => (
                    <div
                      key={idx}
                      className={`log-entry ${entry.name === 'SYS_ERRORS' ? 'log-entry-error' : ''}`}
                    >
                      {formatWatcherTimestamp(entry.timestamp)} &mdash; {entry.topic || entry.name}
                      {entry.name === 'SYS_ERRORS'
                        ? `: ${entry.error}`
                        : ` — ${formatWatcherValues(entry)}`}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

export default Debug;
