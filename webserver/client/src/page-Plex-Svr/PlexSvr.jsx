/*
 * Plex Server Control Interface
 * ============================
 * 
 * This webpage provides a user-friendly interface to control a Synology NAS server
 * that hosts a Plex media server for power management and energy savings.
 * 
 * HOW IT WORKS:
 * 
 * 1. SERVER COMMUNICATION:
 *    - Communicates with a backend API server that manages the physical Synology NAS
 *    - Uses REST API calls to check status, power on/off, and schedule shutdowns
 *    - Backend handles Wake-on-LAN for powering on and SSH commands for shutdown
 * 
 * 2. POWER STATES:
 *    - OFF: Server is completely powered down
 *    - ON (Manual): Server is on and stays on until manually turned off
 *    - ON (Timed): Server is on for a specific duration (2, 3, or 4 hours)
 * 
 * 3. AUTOMATIC SHUTDOWN:
 *    - Server-side timers handle automatic shutdown (not client-side)
 *    - Scheduled shutdown time is stored on the server for reliability
 *    - Client displays countdown timer and wall clock shutdown time
 *    - Automatic shutdown works even if browser is closed
 * 
 * 4. STATUS DETECTION:
 *    - Differentiates between server:
 *      - being on
 *      - just network bd on and ready for wake-on-LAN packet
 *      - unreachable/offline (either powered off or network bd off)
 *    - Checks for active services (DSM web interface, authentication, etc.)
 *    - Displays appropriate messages based on ethernet connectivity status
 * 
 * 5. USER INTERFACE:
 *    - Radio buttons for power state selection
 *    - Real-time status messages with color coding
 *    - Live countdown timer with wall clock time display
 *    - Error indicators for manual restart situations
 * 
 * 6. SMART BEHAVIOR:
 *    - Avoids unnecessary power commands if server is already in desired state
 *    - Persists radio button selection across page reloads
 *    - Handles network errors and provides user feedback
 *    - Updates timer display when switching between timed options
 */

import React, { useState, useEffect, useRef } from 'react';
import { Header, Icon, Form, Radio, Container, Segment, Message } from 'semantic-ui-react';
import './PlexSvr.css';
import { getServerUrl } from '../utils/api';

const PlexSvr = () => {
  const [selectedOption, setSelectedOption] = useState('standby');
  const [message, setMessage] = useState('');
  const [scheduledTime, setScheduledTime] = useState(null);
  const [timeRemaining, setTimeRemaining] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const timerRef = useRef(null);

  // Control Kasa power outlet 4 (for additional power management)
  const controlKasaOutlet4 = async (action) => {
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/kasa/4`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action: action }),
      });
      
      if (response.ok) {
        const result = await response.json();
        console.log(`Kasa outlet 4 ${action}: ${result.success ? 'SUCCESS' : 'FAILED'}`);
        if (result.success) {
          console.log(`Kasa outlet 4 message: ${result.message}`);
        }
        return result.success;
      }
    } catch (error) {
      console.error(`Error controlling Kasa outlet 4: ${error.message}`);
    }
    return false;
  };

  // Control multiple Kasa outlets (2=TV, 3=Soundbar, 4=Synology)
  const controlKasaEntertainmentSystem = async (action) => {
    console.log(`Turning ${action} entertainment system outlets: 2 (TV), 3 (Soundbar), 4 (Synology)`);
    
    const outlets = [2, 3, 4];
    const results = await Promise.all(
      outlets.map(async (outlet) => {
        try {
          const response = await fetch(`${getServerUrl()}/api/debug/kasa/${outlet}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ action: action }),
          });
          
          if (response.ok) {
            const result = await response.json();
            console.log(`Kasa outlet ${outlet} ${action}: ${result.success ? 'SUCCESS' : 'FAILED'}`);
            if (result.success) {
              console.log(`Kasa outlet ${outlet} message: ${result.message}`);
            }
            return { outlet, success: result.success };
          }
        } catch (error) {
          console.error(`Error controlling Kasa outlet ${outlet}: ${error.message}`);
        }
        return { outlet, success: false };
      })
    );
    
    const successCount = results.filter(r => r.success).length;
    console.log(`Entertainment system power ${action}: ${successCount}/${outlets.length} outlets succeeded`);
    
    return results;
  };

  // Control Synology NAS
  const controlSynology = async (action) => {
    try {
      console.log(`Sending ${action} command to Synology NAS...`);
      setMessage(`Processing...`);
      
      const response = await fetch(`${getServerUrl()}/api/debug/synology/${action}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      
      if (result.success) {
        // Use shorter, cleaner messages for user display
        if (action === 'power-off') {
          setMessage('Ready');
        } else if (action === 'power-on') {
          setMessage('Server on');
        } else {
          setMessage(`Done`);
        }
        return true;
      } else {
        setMessage(`${action} failed: ${result.message}`);
        return false;
      }
    } catch (error) {
      console.error('Error controlling Synology NAS:', error);
      setMessage(`Error communicating with Synology NAS: ${error.message}`);
      return false;
    }
  };

  // Get scheduled shutdown time from server
  const getScheduledTime = async () => {
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/synology/scheduled-time`);
      if (response.ok) {
        const result = await response.json();
        if (result.success) {
          setScheduledTime(result.scheduled_time);
          return result.scheduled_time;
        }
      }
    } catch (error) {
      console.error('Error getting scheduled time:', error);
    }
    return null;
  };

  // Schedule shutdown on server
  const scheduleShutdown = async (hours) => {
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/synology/schedule-shutdown`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ hours }),
      });
      
      if (response.ok) {
        const result = await response.json();
        if (result.success) {
          setScheduledTime(result.scheduled_time);
          return result.scheduled_time; // Return the actual timestamp
        }
      }
    } catch (error) {
      console.error('Error scheduling shutdown:', error);
    }
    return false;
  };

  // Cancel scheduled shutdown
  const cancelScheduledShutdown = async () => {
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/synology/scheduled-time`, {
        method: 'DELETE',
      });
      
      if (response.ok) {
        const result = await response.json();
        if (result.success) {
          setScheduledTime(null);
          return true;
        }
      }
    } catch (error) {
      console.error('Error cancelling scheduled shutdown:', error);
    }
    return false;
  };

  // Check if server is currently running (without changing UI state)
  const isServerCurrentlyRunning = async () => {
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/synology/status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        return false;
      }
      
      const result = await response.json();
      
      if (result.success && result.message) {
        const messageText = String(result.message).toLowerCase();
        
        // Look for indicators that server is actually running/responding to services
        return messageText.includes('running') || 
               messageText.includes('online') || 
               messageText.includes('logged in') ||
               messageText.includes('authenticated') ||
               messageText.includes('web interface') ||
               messageText.includes('dsm') ||
               (messageText.includes('status') && messageText.includes('ok'));
      }
    } catch (error) {
      console.error('Error checking server status:', error);
    }
    return false;
  };

  // Check server status on component load
  const checkServerStatus = async () => {
    let serverIsOn = false; // Declare local variable
    
    try {
      setIsLoading(true);
      setMessage('Checking server status...');
      
      const response = await fetch(`${getServerUrl()}/api/debug/synology/status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      
      if (result.success) {
        // Check the message field for actual server status indicators
        if (result.message) {
          const messageText = String(result.message).toLowerCase();
          
          // Look for indicators that server is actually running/responding to services
          // NOT just network reachable (which could be just WoL capability)
          serverIsOn = messageText.includes('running') || 
                      messageText.includes('online') || 
                      messageText.includes('logged in') ||
                      messageText.includes('authenticated') ||
                      messageText.includes('web interface') ||
                      messageText.includes('dsm') ||
                      (messageText.includes('status') && messageText.includes('ok'));
        }
        
        if (serverIsOn) {
          // Don't set the radio button here - let getScheduledTime determine if it's timed or manual
          setMessage("Ready");
        } else {
          setSelectedOption('standby');
          // Check if ethernet is active by parsing the message text
          let ethernetActive = false;
          if (result.message) {
            const messageText = String(result.message).toLowerCase();
            // Look for "ethernet: active" or "ethernet:      active" in the message
            ethernetActive = messageText.includes('ethernet:') && 
                           messageText.includes('active') &&
                           !messageText.includes('inactive');
          }
          
          if (ethernetActive) {
            setMessage("Ready");
          } else {
            setMessage("Server off — must manually restart server (behind TV)");
            // Turn on entertainment system outlets when ethernet is unavailable (manual restart needed)
            controlKasaEntertainmentSystem('on');
          }
        }
      } else {
        setMessage(`❌ Unable to determine server status: ${result.message || 'Unknown error'}`);
        setSelectedOption('standby');
      }
      
      // Also get scheduled shutdown time and update radio selection
      const scheduledTime = await getScheduledTime();
      
      // If server is on and there's a scheduled time, set appropriate radio button
      if (serverIsOn && scheduledTime) {
        const now = Date.now() / 1000;
        const remainingSeconds = scheduledTime - now;
        
        // Calculate the original duration by determining which standard duration (2, 3, or 4 hours)
        // the scheduled time is closest to. This preserves the original choice even when countdown
        // goes below the initial selection.
        const possibleDurations = [2, 3, 4]; // hours
        let bestMatch = 'manual';
        let smallestDifference = Infinity;
        
        for (const duration of possibleDurations) {
          // Calculate what the remaining time would be if this was the original choice
          // Allow some tolerance for processing delays and network latency
          const expectedRemainingForDuration = duration * 3600;
          const timeSinceScheduled = expectedRemainingForDuration - remainingSeconds;
          
          // If the time since scheduled is reasonable (between 0 and the full duration)
          // and this is closer than our previous best match
          if (timeSinceScheduled >= 0 && timeSinceScheduled <= expectedRemainingForDuration) {
            const difference = Math.abs(expectedRemainingForDuration - (remainingSeconds + timeSinceScheduled));
            if (difference < smallestDifference) {
              smallestDifference = difference;
              bestMatch = `${duration}hr`;
            }
          }
        }
        
        // If remaining time is greater than 4 hours, it's likely a manual setting with a very long timer
        // If less than 30 seconds, just show the closest hour option to avoid confusion
        if (remainingSeconds > 4.5 * 3600) {
          setSelectedOption('manual');
        } else if (remainingSeconds < 30) {
          // For very short remaining times, determine the closest standard duration
          const remainingHours = remainingSeconds / 3600;
          if (remainingHours <= 2.5) {
            setSelectedOption('2hr');
          } else if (remainingHours <= 3.5) {
            setSelectedOption('3hr');
          } else {
            setSelectedOption('4hr');
          }
        } else {
          setSelectedOption(bestMatch);
        }
      } else if (serverIsOn && !scheduledTime) {
        setSelectedOption('manual');
      }
      
    } catch (error) {
      console.error('Error checking server status:', error);
      setMessage('Error checking server status - assuming server is off');
      setSelectedOption('off');
    } finally {
      setIsLoading(false);
    }
  };

  // Start countdown timer based on scheduled time
  const startTimer = (useScheduledTime = null) => {
    // Clear any existing timer
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }

    const targetTime = useScheduledTime || scheduledTime;
    if (!targetTime) {
      setTimeRemaining(0);
      return;
    }
    
    timerRef.current = setInterval(() => {
      const now = Date.now() / 1000; // Convert to seconds
      const remaining = Math.max(0, Math.floor(targetTime - now));
      
      setTimeRemaining(remaining);
      
      if (remaining <= 0) {
        // Timer expired, turn off server
        controlSynology('power-off');
        setSelectedOption('standby');
        setScheduledTime(null);
        setMessage('Synology Plex Server off');
        clearInterval(timerRef.current);
      }
    }, 1000);
  };

  // Handle radio button change
  const handleChange = async (e, { value }) => {
    setSelectedOption(value);
    
    // Clear any existing timer
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (value === 'standby') {
      // Graceful shutdown — keeps network board powered, WoL-ready
      await cancelScheduledShutdown();
      await controlSynology('power-off');
      setTimeRemaining(0);
    } else if (value === 'manual') {
      // Turn on and leave on (cancel any scheduled shutdown)
      await cancelScheduledShutdown();
      
      // Check if server is already running
      const serverRunning = await isServerCurrentlyRunning();
      if (serverRunning) {
        setMessage('✅ Server running');
      } else {
        await controlSynology('power-on');
      }
      setTimeRemaining(0);
    } else if (value.endsWith('hr')) {
      // Timed options - turn on and schedule shutdown
      const hours = parseInt(value.replace('hr', ''));
      
      // Check if server is already running
      const serverRunning = await isServerCurrentlyRunning();
      let success = true;
      
      if (serverRunning) {
        setMessage(`Server on - turns off in ${hours} hours`);
      } else {
        success = await controlSynology('power-on');
        if (success) {
          setMessage(`Server on for ${hours} hours`);
        }
      }
      
      if (success) {
        const newScheduledTime = await scheduleShutdown(hours);
        if (newScheduledTime) {
          // Use the fresh scheduled time directly to avoid React state timing issues
          startTimer(newScheduledTime);
        }
      }
    }
  };

  // Format time remaining for display
  const formatTime = (seconds) => {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    let countdown = '';
    if (hours > 0) {
      countdown = `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } else {
      countdown = `${mins}:${secs.toString().padStart(2, '0')}`;
    }
    
    // Add wall clock time if we have a scheduled time
    if (scheduledTime) {
      const shutoffTime = new Date(scheduledTime * 1000).toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit' 
      });
      return `${countdown} remaining (turns off at ${shutoffTime})`;
    }
    
    return countdown;
  };

  // Cleanup timer on unmount and check server status on mount
  useEffect(() => {
    // Check server status when component mounts
    checkServerStatus();
    
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Start timer when scheduledTime changes
  useEffect(() => {
    if (scheduledTime) {
      startTimer();
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      setTimeRemaining(0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduledTime]);

  return (
    <div className="plex-svr-page">
      <Header as="h1" icon textAlign="center">
        <Icon name="tv" />
        <Header.Content>
          Local Plex Server
          <Header.Subheader>Turns the local Plex server on/off for power savings (10 Watts)</Header.Subheader>
        </Header.Content>
      </Header>
      
      <Container>
        <Segment>
          {isLoading && (
            <Message icon>
              <Icon name="circle notched" loading />
              <Message.Content>
                <Message.Header>Loading</Message.Header>
                Checking server status...
              </Message.Content>
            </Message>
          )}
          
          {!isLoading && message && (
            <Message negative={message.includes('must be restarted manually')}>
              {message}
              {timeRemaining > 0 && (
                <div style={{ marginTop: '10px', fontWeight: 'bold' }}>
                  Time remaining: {formatTime(timeRemaining)}
                </div>
              )}
            </Message>
          )}
          
          <Form>
            <Form.Field>
              <Radio
                label='Standby (ready to start)'
                name='plexServerOption'
                value='standby'
                checked={selectedOption === 'standby'}
                onChange={handleChange}
                disabled={isLoading}
              />
            </Form.Field>
            <Form.Field>
              <Radio
                label='On for 2 hours'
                name='plexServerOption'
                value='2hr'
                checked={selectedOption === '2hr'}
                onChange={handleChange}
                disabled={isLoading}
              />
            </Form.Field>
            <Form.Field>
              <Radio
                label='On for 3 hours'
                name='plexServerOption'
                value='3hr'
                checked={selectedOption === '3hr'}
                onChange={handleChange}
                disabled={isLoading}
              />
            </Form.Field>
            <Form.Field>
              <Radio
                label='On for 4 hours'
                name='plexServerOption'
                value='4hr'
                checked={selectedOption === '4hr'}
                onChange={handleChange}
                disabled={isLoading}
              />
            </Form.Field>
            <Form.Field>
              <Radio
                label='On until I turn off'
                name='plexServerOption'
                value='manual'
                checked={selectedOption === 'manual'}
                onChange={handleChange}
                disabled={isLoading}
              />
            </Form.Field>
          </Form>
        </Segment>
      </Container>
    </div>
  );
};

export default PlexSvr;
