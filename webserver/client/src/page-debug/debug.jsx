import React, { useEffect, useState } from "react";
import './debug.css';
import { getServerUrl } from '../utils/api';

console.log("Debug component loaded");

function Debug() {
  const [usbPorts, setUsbPorts] = useState({});
  const [kasaOutlets, setKasaOutlets] = useState({});
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
        return data;
      } else {
        setMessage(data.message || 'Failed to fetch USB status');
        return data;
      }
    } catch (error) {
      console.error('Error fetching USB status:', error);
      setMessage('Failed to fetch USB status: ' + error.message);
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
        return data;
      } else {
        console.log('getKasaStatus: Response not successful:', data.message);
        setMessage(data.message || 'Failed to fetch Kasa status');
        return data;
      }
    } catch (error) {
      console.error('Error fetching Kasa status:', error);
      setMessage('Failed to fetch Kasa status: ' + error.message);
      return { success: false, message: 'Failed to fetch Kasa status: ' + error.message };
    }
  };

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
          <h2>USB Ports (Internet Access)</h2>
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
          <h2>Kasa Power Strip</h2>
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
                  className="action-button power-off-button"
                  onClick={() => controlSynology('power-off')}
                >
                  Power Off
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Debug;
