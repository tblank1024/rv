/**
 * RV Security Internet Connection Management Page
 * 
 * This page provides a unified interface for managing multiple internet connection types
 * in an RV environment. It controls both USB hub ports and Kasa power strip outlets
 * to enable/disable different internet connection hardware.
 * 
 * === SUPPORTED CONNECTION TYPES ===
 * - Cellular: USB port 1, basic cellular modem
 * - Cellular + Amp: USB port 1 + Kasa port 1 (cellular with signal amplifier)
 * - WiFi: USB port 2, WiFi adapter
 * - Starlink: USB port 3 + Kasa port 6 (satellite internet)
 * - Wired: USB port 4, ethernet adapter
 * - None: All ports off
 * 
 * === HOW IT WORKS ===
 * 1. User selects a connection type via radio buttons
 * 2. System automatically executes a 3-step process:
 *    a) Power Control: Activates the correct USB port and Kasa outlets
 *    b) Initialization Wait: Waits for hardware to initialize (varies by type)
 *    c) Connectivity Test: Pings 8.8.8.8 to verify internet connectivity
 * 
 * === USB HUB CONTROL ===
 * - Uses a CoolGear USB hub with ASCII command interface
 * - Implements mutual exclusion (only one port active at a time)
 * - Each connection type maps to a specific USB port
 * - Initialization delays vary by connection type (cellular: 5s, starlink: 20s, etc.)
 * 
 * === KASA POWER STRIP INTEGRATION ===
 * - Port 1: Cellular signal amplifier (only for cellular-amp)
 * - Port 6: Starlink power supply (only for starlink)
 * - All other connection types: both Kasa ports OFF
 * - Provides power consumption monitoring
 * 
 * === CONNECTIVITY TESTING ===
 * - Uses system ping command to 8.8.8.8
 * - Connection-specific settling delays before testing
 * - Real-time status updates with success/warning/error states
 * 
 * === WIFI CONFIGURATION ===
 * - Separate section for configuring WiFi credentials
 * - Communicates with Raspberry Pi Zero 2W bridge device
 * - Supports permanent profile storage
 * 
 * === STATE MANAGEMENT ===
 * - Loads current connection state on page load
 * - Supports operation interruption/cancellation
 * - Auto-tests connectivity when status is unknown
 * - Real-time power consumption monitoring for Kasa outlets
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Form, Button, Message, Card, Header, Icon, Segment, Radio, TextArea, Checkbox } from 'semantic-ui-react';
import './Internet.css';
import { fetchFromServer } from '../utils/api';

const Internet = () => {
  const [selectedOption, setSelectedOption] = useState('none');
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState(null);
  const [statusMessage, setStatusMessage] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [abortController, setAbortController] = useState(null);

  // WiFi configuration states
  const [ssid, setSsid] = useState('');
  const [password, setPassword] = useState('');
  const [permanentStore, setPermanentStore] = useState(false);
  const [output, setOutput] = useState('');
  const [wifiLoading, setWifiLoading] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  // Power reading states
  const [kasaPort1Power, setKasaPort1Power] = useState(0);
  const [kasaPort6Power, setKasaPort6Power] = useState(0);

  const internetOptions = [
    { value: 'cellular', text: 'Cellular', port: 1, waitTime: 60, kasaPort: null },
    { value: 'cellular-amp', text: 'Cellular + Amp', port: 1, waitTime: 60, kasaPort: 1 },
    { value: 'wifi', text: 'WiFi', port: 2, waitTime: 30, kasaPort: null },
    { value: 'starlink', text: 'Starlink', port: 3, waitTime: 120, kasaPort: 6 },
    { value: 'wired', text: 'Wired', port: 4, waitTime: 30, kasaPort: null },
    { value: 'none', text: 'None', port: 0, waitTime: 0, kasaPort: null }
  ];

  useEffect(() => {
    let interval;
    if (countdown > 0) {
      interval = setInterval(() => {
        setCountdown(prev => prev - 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [countdown]);

  // Fetch current internet connection status on component mount
  useEffect(() => {
    const fetchCurrentStatus = async () => {
      try {
        const response = await fetchFromServer('/api/internet/status');
        if (response.current_connection) {
          setSelectedOption(response.current_connection);
          console.log('Loaded current internet connection:', response.current_connection);
        }
      } catch (error) {
        console.error('Failed to fetch current internet status:', error);
        // Keep default 'none' if fetch fails
      }
    };

    fetchCurrentStatus();
  }, []); // Empty dependency array means this runs once on mount

  const handleOptionChange = (e, { value }) => {
    // Always allow changing the selection - this will interrupt any ongoing operations
    setSelectedOption(value);
    setConnectionStatus(null);
    setStatusMessage('');
    setCountdown(0);
    
    // Abort any ongoing operation
    if (abortController) {
      abortController.abort();
    }
    
    // Reset states
    setIsConnecting(false);
    
    // Automatically execute the selected action
    setTimeout(() => {
      executeAction(value);
    }, 100); // Small delay to ensure UI updates
  };

  const executeAction = async (selectedValue) => {
    if (!selectedValue) return;

    const option = internetOptions.find(opt => opt.value === selectedValue);
    if (!option) return;

    // Create new AbortController for this operation
    const newAbortController = new AbortController();
    setAbortController(newAbortController);

    // Handle "None" option - just power off all ports
    if (selectedValue === 'none') {
      setIsConnecting(true);
      setConnectionStatus(null);
      setStatusMessage('Powering off all internet connections...');

      try {
        const response = await fetchFromServer('/api/internet/power', {
          method: 'POST',
          body: JSON.stringify({
            port: 0, // 0 means all ports off
            action: 'off',
            kasaPort: null,
            connection_type: 'none'
          }),
          signal: newAbortController.signal
        });

        if (newAbortController.signal.aborted) return;

        if (response.success) {
          setConnectionStatus('info');
          setStatusMessage('🔌 All internet connections powered off');
        } else {
          throw new Error(response.message || 'Failed to power off ports');
        }

      } catch (error) {
        if (newAbortController.signal.aborted) return;
        console.error('Power off error:', error);
        setConnectionStatus('error');
        setStatusMessage(`❌ Failed to power off connections: ${error.message}`);
      } finally {
        setIsConnecting(false);
        setAbortController(null);
      }
      return;
    }

    // Handle regular connection options
    setIsConnecting(true);
    setConnectionStatus(null);
    setStatusMessage(`Connecting to ${option.text}...`);

    try {
      // Step 1: Power on the selected port and turn off others
      setStatusMessage(`Powering on ${option.text} (Port ${option.port})...`);
      
      const powerResponse = await fetchFromServer('/api/internet/power', {
        method: 'POST',
        body: JSON.stringify({
          port: option.port,
          action: 'on',
          kasaPort: option.kasaPort,
          connection_type: option.value
        }),
        signal: newAbortController.signal
      });

      if (newAbortController.signal.aborted) return;

      if (!powerResponse.success) {
        throw new Error(powerResponse.message || 'Failed to power on port');
      }

      // Step 2: Wait for the specified time with countdown (but check for abort)
      setStatusMessage(`Waiting for ${option.text} to initialize...`);
      setCountdown(option.waitTime);
      
      // Use a more granular wait that can be interrupted
      for (let i = option.waitTime; i > 0; i--) {
        if (newAbortController.signal.aborted) return;
        await new Promise(resolve => setTimeout(resolve, 1000));
        if (newAbortController.signal.aborted) return;
        setCountdown(i - 1);
      }

      if (newAbortController.signal.aborted) return;

      // Step 3: Test internet connectivity
      setStatusMessage(`Testing internet connectivity...`);
      setCountdown(0);
      
      const testResponse = await fetchFromServer('/api/internet/test', {
        method: 'POST',
        body: JSON.stringify({
          connection_type: selectedValue
        }),
        signal: newAbortController.signal
      });

      if (newAbortController.signal.aborted) return;

      if (testResponse.success && testResponse.connected) {
        setConnectionStatus('success');
        setStatusMessage(`Connected - Internet Verified`);
      } else {
        setConnectionStatus('warning');
        setStatusMessage(`⚠️ ${option.text} powered on, but internet connectivity could not be verified. ${testResponse.message || ''}`);
      }

    } catch (error) {
      if (newAbortController.signal.aborted) return;
      console.error('Connection error:', error);
      setConnectionStatus('error');
      setStatusMessage(`❌ Failed to connect via ${option.text}: ${error.message}`);
    } finally {
      setIsConnecting(false);
      setAbortController(null);
    }
  };

  // WiFi configuration functions
  const handleWifiSubmit = async (e) => {
    e.preventDefault();
    
    if (!ssid.trim()) {
      setOutput('Error: SSID is required');
      return;
    }
    
    if (!password.trim()) {
      setOutput('Error: Password is required');
      return;
    }

    setWifiLoading(true);
    setOutput('Sending WiFi configuration to RP2W...\n');
    
    try {
      const requestData = {
        ssid: ssid.trim(),
        password: password.trim(),
        permanent: permanentStore
      };

      const response = await fetchFromServer('/api/wifi-config', {
        method: 'POST',
        body: JSON.stringify(requestData)
      });

      let resultMessage = '';
      let resultType = 'info';
      
      // Handle different exit codes based on the Python script
      switch (response.exit_code) {
        case 0:
          resultMessage = 'Success: WiFi connected and configuration saved!';
          resultType = 'success';
          break;
        case 1:
          resultMessage = 'Error: General failure (connection, invalid packet, or server error)';
          resultType = 'error';
          break;
        case 100:
          resultMessage = 'Warning: SSID/Password updated but activation failed (likely bad password)';
          resultType = 'warning';
          break;
        case 101:
          resultMessage = 'Warning: SSID/Password updated but WiFi connection failed (bad/unreachable SSID or timeout)';
          resultType = 'warning';
          break;
        default:
          resultMessage = `Unknown result: Exit code ${response.exit_code}`;
          resultType = 'info';
      }

      setLastResult({ type: resultType, message: resultMessage });
      setOutput(prev => prev + `\nResponse from RP2W:\n${response.output}\n\n${resultMessage}`);
      
    } catch (error) {
      const errorMessage = `Error communicating with server: ${error.message}`;
      setLastResult({ type: 'error', message: errorMessage });
      setOutput(prev => prev + `\n${errorMessage}`);
    } finally {
      setWifiLoading(false);
    }
  };

  // Function to fetch power readings from Kasa power strip
  const fetchKasaPower = useCallback(async () => {
    try {
      // Fetch power from port 1 (cellular amp)
      const port1Response = await fetchFromServer('/api/kasa/power/1');
      if (port1Response.success) {
        setKasaPort1Power(port1Response.power);
      }

      // Fetch power from port 6 (starlink)
      const port6Response = await fetchFromServer('/api/kasa/power/6');
      if (port6Response.success) {
        setKasaPort6Power(port6Response.power);
      }
    } catch (error) {
      console.error('Failed to fetch Kasa power readings:', error);
    }
  }, []);

  // Fetch power readings only on component mount (page load/refresh)
  useEffect(() => {
    fetchKasaPower();
  }, [fetchKasaPower]);

  // Function to get power consumption text for each option
  const getPowerText = useCallback((option) => {
    const isSelected = selectedOption === option.value;
    
    switch (option.value) {
      case 'cellular':
        return isSelected ? 'Actual: 2 Watts' : 'Est: 2 Watts';
      case 'cellular-amp':
        return isSelected ? `Actual: ${2 + kasaPort1Power} Watts` : 'Est: 54 Watts';
      case 'wifi':
        return isSelected ? 'Actual: 0.7 Watts' : 'Est: 0.7 Watts';
      case 'starlink':
        return isSelected ? `Actual: ${kasaPort6Power} Watts` : 'Est: 120 Watts';
      case 'wired':
        return isSelected ? 'Actual: 0.1 Watts' : 'Est: 0.1 Watts';
      case 'none':
        return isSelected ? 'Actual: 0 Watts' : 'Est: 0 Watts';
      default:
        return isSelected ? 'Actual: 0 Watts' : 'Est: 0 Watts';
    }
  }, [kasaPort1Power, kasaPort6Power, selectedOption]);

  // Function to automatically test connectivity when status is "Not tested"
  const autoTestConnectivity = useCallback(async () => {
    if (selectedOption && selectedOption !== 'none' && connectionStatus === null) {
      try {
        setStatusMessage('Running automatic connectivity test...');
        const testResponse = await fetchFromServer('/api/internet/test', {
          method: 'POST',
          body: JSON.stringify({
            connection_type: selectedOption
          })
        });

        if (testResponse.success) {
          if (testResponse.connected) {
            setConnectionStatus('success');
            setStatusMessage('Connected \& Verified');
          } else {
            setConnectionStatus('warning');
            setStatusMessage('⚠️ Port active but no internet connectivity detected');
          }
        } else {
          setConnectionStatus('error');
          setStatusMessage(`❌ Connectivity test failed: ${testResponse.message}`);
        }
      } catch (error) {
        console.error('Auto connectivity test error:', error);
        setConnectionStatus('error');
        setStatusMessage(`❌ Auto test failed: ${error.message}`);
      }
    }
  }, [selectedOption, connectionStatus]);

  // Automatically test connectivity when status is "Not tested"
  useEffect(() => {
    if (selectedOption && selectedOption !== 'none' && connectionStatus === null && !isConnecting) {
      const timer = setTimeout(() => {
        autoTestConnectivity();
      }, 2000); // Wait 2 seconds before auto-testing
      
      return () => clearTimeout(timer);
    }
  }, [selectedOption, connectionStatus, isConnecting, autoTestConnectivity]);

  const clearWifiOutput = () => {
    setOutput('');
    setLastResult(null);
  };

  const clearWifiForm = () => {
    setSsid('');
    setPassword('');
    setPermanentStore(false);
  };

  const getStatusIcon = () => {
    switch (connectionStatus) {
      case 'success': return 'check circle';
      case 'warning': return 'warning circle';
      case 'error': return 'times circle';
      case 'info': return 'info circle';
      default: return 'wifi';
    }
  };

  const getStatusColor = () => {
    switch (connectionStatus) {
      case 'success': return 'green';
      case 'warning': return 'yellow';
      case 'error': return 'red';
      case 'info': return 'blue';
      default: return 'grey';
    }
  };

  return (
    <div className="internet-page">
      <div className="internet-container">
        <Header as="h1" icon textAlign="center">
          <Icon name="wifi" />
          <Header.Content>
            Internet Connection Control
            <Header.Subheader>Select and manage your internet connection method</Header.Subheader>
          </Header.Content>
        </Header>

        <Card className="internet-control-card">
          <Card.Content>
            <Form>
              <Form.Field>
                <label className="internet-connection-label">Select Internet Connection:</label>
                {internetOptions.map(option => (
                  <Form.Field key={option.value}>
                    <Radio
                      label={`${option.text} (${getPowerText(option)})`}
                      name="internetOption"
                      value={option.value}
                      checked={selectedOption === option.value}
                      onChange={handleOptionChange}
                      disabled={false}  // Always allow changing selection
                    />
                  </Form.Field>
                ))}
              </Form.Field>
            </Form>
            
            {/* Internet Status at bottom of connection selection */}
            <div style={{ marginTop: '15px', paddingTop: '15px', borderTop: '1px solid #e0e0e0' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <strong>Internet Status:</strong>
                <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  {isConnecting ? (
                    <>
                      <Icon name="circle notched" loading />
                      Initializing...
                    </>
                  ) : connectionStatus === 'success' ? (
                    <>
                      <Icon name="check circle" color="green" />
                      Connected & Verified
                    </>
                  ) : connectionStatus === 'warning' ? (
                    <>
                      <Icon name="warning circle" color="yellow" />
                      Port Active, Connectivity Unknown
                    </>
                  ) : connectionStatus === 'error' ? (
                    <>
                      <Icon name="times circle" color="red" />
                      Failed
                    </>
                  ) : (
                    <>
                      <Icon name="circle outline" />
                      Not tested
                    </>
                  )}
                  {countdown > 0 && (
                    <span className="countdown-badge" style={{ marginLeft: '10px', padding: '2px 8px', backgroundColor: '#f0f0f0', borderRadius: '12px', fontSize: '0.8em' }}>
                      {countdown}s
                    </span>
                  )}
                </span>
              </div>
            </div>
          </Card.Content>
        </Card>

        {/* Starlink Power Warning */}
        {selectedOption === 'starlink' && (
          <Message 
            color="red"
            icon="warning sign"
            header="Important Notice"
            content="Be sure Power is applied"
            style={{ marginBottom: '15px' }}
          />
        )}

        {/* Status Message Display */}
        {statusMessage && connectionStatus !== 'success' && (
          <Message 
            color={getStatusColor()}
            icon={getStatusIcon()}
            header={connectionStatus === 'warning' ? 'Partial Success' : 
                    connectionStatus === 'error' ? 'Connection Failed' : 
                    connectionStatus === 'info' ? 'Information' : 'Status'}
            content={statusMessage}
          />
        )}

        {/* WiFi Configuration Section */}
        {selectedOption === 'wifi' && (
          <div style={{ marginBottom: '20px' }}>
            <Card className="wifi-config-card">
              <Card.Content>
                <Card.Header>WiFi Configuration</Card.Header>
                <Card.Description>
                  Configure WiFi settings for RP2W device
                </Card.Description>
              </Card.Content>
              <Card.Content>
                <Form onSubmit={handleWifiSubmit}>
                  <Form.Field required>
                    <label>SSID (Network Name)</label>
                    <Form.Input
                      placeholder="Enter WiFi network name"
                      value={ssid}
                      onChange={(e) => setSsid(e.target.value)}
                      disabled={wifiLoading}
                      icon="wifi"
                      iconPosition="left"
                    />
                  </Form.Field>
                  
                  <Form.Field required>
                    <label>Password</label>
                    <Form.Input
                      type="password"
                      placeholder="Enter WiFi password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={wifiLoading}
                      icon="lock"
                      iconPosition="left"
                    />
                  </Form.Field>

                  <Form.Field>
                    <Checkbox
                      label="Permanently store this SSID/Password pair in RP2W"
                      checked={permanentStore}
                      onChange={(e, { checked }) => setPermanentStore(checked)}
                      disabled={wifiLoading}
                    />
                  </Form.Field>

                  <div className="wifi-form-buttons">
                    <Button 
                      type="submit" 
                      primary 
                      loading={wifiLoading}
                      disabled={wifiLoading || !ssid.trim() || !password.trim()}
                      icon="send"
                      labelPosition="left"
                      content="Send Configuration"
                    />
                    <Button 
                      type="button" 
                      secondary 
                      onClick={clearWifiForm}
                      disabled={wifiLoading}
                      icon="refresh"
                      content="Clear Form"
                    />
                  </div>
                </Form>
              </Card.Content>
            </Card>

            <Card className="wifi-output-card" style={{ marginTop: '15px' }}>
              <Card.Content>
                <Card.Header>
                  WiFi Output
                  <Button 
                    floated="right" 
                    size="mini" 
                    onClick={clearWifiOutput}
                    disabled={wifiLoading}
                    icon="trash"
                    content="Clear"
                  />
                </Card.Header>
              </Card.Content>
              <Card.Content>
                {lastResult && (
                  <Message 
                    color={lastResult.type === 'success' ? 'green' : 
                           lastResult.type === 'warning' ? 'yellow' : 
                           lastResult.type === 'error' ? 'red' : 'blue'}
                    icon={lastResult.type === 'success' ? 'check circle' : 
                          lastResult.type === 'warning' ? 'warning circle' : 
                          lastResult.type === 'error' ? 'times circle' : 'info circle'}
                    header={lastResult.type === 'success' ? 'Success' : 
                            lastResult.type === 'warning' ? 'Warning' : 
                            lastResult.type === 'error' ? 'Error' : 'Information'}
                    content={lastResult.message}
                  />
                )}
                
                <Segment className="output-segment">
                  <TextArea
                    value={output}
                    placeholder="WiFi configuration output will appear here..."
                    style={{ width: '100%', minHeight: '200px' }}
                    readOnly
                  />
                </Segment>
              </Card.Content>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};

export default Internet;
