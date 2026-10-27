import React, { useEffect, useState } from "react";
import './debug.css';
import { getServerUrl } from '../utils/api';
import { maxWattsDetailed } from '../utils/power';
import PinGate from '../components/PinPrompt';
import SecurityCard from '../components/SecurityCard';

console.log("Debug component loaded");

// A socket's display label: the map's cosmetic "name" if it has one, else its
// WAN role. The two are separate on purpose -- naming socket 1 "Wifi" must not
// put it in the exclusive WAN group, or selecting another uplink would cut
// power to the WiFi adapter.
const socketLabel = (sock) => sock.name || sock.wan || '';

function DebugPanel() {
  const [hubSockets, setHubSockets] = useState({});
  const [hubConfigured, setHubConfigured] = useState(null);
  const [hubConnected, setHubConnected] = useState(null);
  const [hubMessage, setHubMessage] = useState('');
  const [hubBusy, setHubBusy] = useState({});
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
  const [firewall, setFirewall] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [lastUpdate, setLastUpdate] = useState(null);
  const [confirmReboot, setConfirmReboot] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [rebooting, setRebooting] = useState(false);


    // Fetch host firewall status. Checks whether the SOPHIE-* chains are
  // actually hooked, not whether the systemd unit is green -- `apply` exits 0
  // even when individual iptables calls fail, which is exactly how Sophie came
  // up unprotected on 2026-10-21 (see firewall/README.md "Traps").
  const getFirewallStatus = async () => {
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/firewall/status`, {
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setFirewall(data);
      return data;
    } catch (error) {
      console.error('Error fetching firewall status:', error);
      setFirewall({ success: false, healthy: false, message: 'Failed to read firewall status: ' + error.message });
      return { success: false };
    }
  };

    // Fetch Kasa outlet status
  const getKasaStatus = async () => {
    console.log('getKasaStatus: Starting request...');
    try {
      const response = await fetch(`${getServerUrl()}/api/debug/kasa/status`, {
        credentials: 'include',
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
        credentials: 'include',
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

  // Fetch the Plugable hub's physical sockets (kernel per-port power).
  const getHubSockets = async () => {
    try {
      const response = await fetch(`${getServerUrl()}/api/hub/sockets`, {
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json();
      if (data.success) {
        setHubSockets(data.sockets || {});
        setHubConfigured(!!data.configured);
        setHubConnected(true);
        setHubMessage(data.message || '');
      } else {
        setHubSockets({});
        setHubConfigured(false);
        setHubConnected(false);
        setHubMessage(data.message || 'Failed to read hub sockets');
      }
      return data;
    } catch (error) {
      console.error('Error fetching hub sockets:', error);
      setHubSockets({});
      setHubConnected(false);
      setHubMessage('Failed to reach the hub API: ' + error.message);
      return { success: false };
    }
  };

  // One socket on or off, the others untouched -- several may be on at once,
  // which is the whole point of this control and why it is a checkbox rather
  // than a radio group. The Internet page uses the exclusive endpoint instead.
  // Moved here from the Home page: a reboot drops every WiFi client on the
  // RV and takes the dashboard down with it, so it belongs behind the
  // diagnostics rather than one tap from the status screen.
  // Moved here from the Home page 2026-10-26. It belongs behind the PIN with
  // the other destructive controls, and the home page should have nothing on
  // it that can interrupt the RV.
  const doRestartContainers = async () => {
    setRestarting(true);
    setMessage('Restarting containers\u2026');
    try {
      const response = await fetch(`${getServerUrl()}/api/system/restart-containers`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await response.json();
      setMessage(data.message || (data.success ? 'Containers restarted.' : 'Restart failed.'));
    } catch (error) {
      // This container restarts itself, so the reply routinely never arrives.
      // A failure here is not evidence the restart did not happen.
      setMessage('Restart requested; no reply received (expected, since this '
                 + 'server restarts itself).');
    } finally {
      setRestarting(false);
    }
  };

  const doReboot = async () => {
    setConfirmReboot(false);
    setRebooting(true);
    try {
      await fetch(`${getServerUrl()}/api/system/reboot`, {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      setMessage('Reboot requested. This page will stop responding shortly.');
    } catch (error) {
      // A reboot often kills the connection before the reply arrives, so a
      // fetch failure here is not evidence that the reboot did not happen.
      console.error('Reboot request error:', error);
      setMessage('Reboot requested; no reply received (expected if it already went down).');
    }
  };

  const controlHubSocket = async (label, on) => {
    setHubBusy(prev => ({ ...prev, [label]: true }));
    // No optimistic update here. A write is a USB control transfer per
    // identity and can take seconds; showing the new state before the kernel
    // confirms it is how a port gets reported on while it is off.
    try {
      const response = await fetch(`${getServerUrl()}/api/hub/socket`, {
        credentials: 'include',
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ socket: String(label), on }),
      });
      const result = await response.json();
      setHubMessage(result.message || '');
      if (result.sockets && Object.keys(result.sockets).length) {
        setHubSockets(result.sockets);
      } else {
        await getHubSockets();
      }
    } catch (error) {
      console.error('Error controlling hub socket:', error);
      setHubMessage(`Error switching socket ${label}: ${error.message}`);
      await getHubSockets();
    } finally {
      setHubBusy(prev => ({ ...prev, [label]: false }));
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
        credentials: 'include',
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
        credentials: 'include',
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
        if (action !== 'status') {
          // Power actions take a while to settle; refresh the displayed state afterwards
          setTimeout(() => controlSynology('status'), 15000);
        }
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

  // Full off: graceful DSM shutdown, wait for it to finish, then cut Kasa outlet 4.
  // The NAS can then only be restarted with its front power button.
  const synologyFullOff = async () => {
    if (!window.confirm('Shut down the NAS and cut its power? It will need its front power button to restart.')) return;
    const post = (action) => fetch(`${getServerUrl()}/api/debug/synology/${action}`, { method: 'POST' }).then(r => r.json());
    try {
      setSynologyMessage('Full off: shutting down NAS...');
      const off = await post('power-off');
      if (!off.success) {
        setSynologyMessage(`Full off aborted, shutdown failed: ${off.message}`);
        return;
      }
      // Wait up to ~2 min for the NAS to stop responding (state leaves ONLINE)
      for (let i = 0; i < 24; i++) {
        setSynologyMessage(`Full off: waiting for NAS to shut down (${i * 5}s)...`);
        await new Promise(r => setTimeout(r, 5000));
        const st = await post('status');
        if (st.success && st.status && st.status.state !== 'ONLINE') {
          // Give DSM a little longer to finish powering down before cutting power
          await new Promise(r => setTimeout(r, 15000));
          await controlKasaOutlet(4, 'off');
          setSynologyMessage('Full off complete: NAS shut down and outlet 4 off.');
          setTimeout(() => controlSynology('status'), 3000);
          return;
        }
      }
      setSynologyMessage('Full off aborted: NAS still responding after 2 minutes; outlet 4 left on.');
    } catch (error) {
      setSynologyMessage(`Full off failed: ${error.message}`);
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
        console.log('useEffect: Calling getKasaStatus and getHubSockets...');
        await Promise.allSettled([getKasaStatus(), getHubSockets(),
                                  getFirewallStatus(),
                                  controlSynology('status')]);
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
    await Promise.all([getKasaStatus(), getHubSockets(), getFirewallStatus()]);
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
        {connected ? 'Comms OK' : 'No Comms'}
      </span>
    );
  };

  // Armed / exposed / unknown. "Exposed" is the case worth shouting about: no
  // INPUT hook means every service on Sophie (dashboard on 8000 with no auth,
  // MQTT, SSH, VNC) answers whoever is on the park or home network.
  const firewallBadge = () => {
    if (!firewall) return null;
    const armed = !!firewall.healthy;
    const exposed = firewall.success && !armed;
    const label = armed ? 'Armed' : (exposed ? 'EXPOSED' : 'Unknown');
    return (
      <span style={{
        marginLeft: '12px', fontSize: '13px', fontWeight: 'bold',
        padding: '2px 8px', borderRadius: '10px',
        backgroundColor: armed ? '#e8f5e9' : '#ffebee',
        color: armed ? '#2e7d32' : '#c62828',
      }}>
        {label}
      </span>
    );
  };

  // One row of the check table: a tick per family, with optional detail text.
  const fwCheck = (ok, detail) => (
    <td className={ok ? 'fw-ok' : 'fw-bad'}>
      {ok ? '\u2713' : '\u2717'}{detail ? ` ${detail}` : ''}
    </td>
  );

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
        {/* Host firewall: first because it is the one card that reports an
            active security problem rather than a device state. */}
        <div className="debug-section">
          <h2>Host Firewall{firewallBadge()}</h2>
          <div style={{marginBottom: '10px', fontSize: '12px', color: '#666'}}>
            Default-deny inbound and forward on every interface except the RV LAN
            side ({(firewall && firewall.trusted ? firewall.trusted : ['lo', 'br0', 'docker0', 'br-+']).join(', ')}).
            Whichever uplink is live &mdash; park WiFi, Starlink, cellular &mdash; is untrusted.
            Rules: <code>firewall/sophie-firewall.sh</code>.
          </div>
          {firewall && !firewall.healthy && firewall.message && (
            <div className="error-text" style={{marginBottom: '10px'}}>{firewall.message}</div>
          )}
          {firewall && firewall.healthy && (
            <div style={{marginBottom: '10px', fontSize: '12px', color: '#2e7d32'}}>{firewall.message}</div>
          )}
          {firewall && firewall.ipv4 && firewall.ipv6 ? (
            <table className="fw-table">
              <thead>
                <tr><th>Check</th><th>IPv4</th><th>IPv6</th></tr>
              </thead>
              <tbody>
                {[
                  ['INPUT \u2192 SOPHIE-IN',
                    (f) => fwCheck(f.input_hooked && f.input_position === 1,
                      f.input_hooked ? `pos ${f.input_position}` : 'not hooked')],
                  ['FORWARD \u2192 SOPHIE-FWD', (f) => fwCheck(f.forward_hooked, f.forward_hooked ? '' : 'not hooked')],
                  ['DOCKER-USER \u2192 SOPHIE-FWD', (f) => fwCheck(f.docker_user_hooked, f.docker_user_hooked ? '' : 'not hooked')],
                  ['FORWARD policy', (f) => fwCheck(f.forward_policy === 'DROP', f.forward_policy)],
                  ['SOPHIE-IN chain', (f) => fwCheck(f.in_chain && f.in_chain.exists,
                    f.in_chain && f.in_chain.exists ? `${f.in_chain.drop_packets} dropped` : 'missing')],
                  ['SOPHIE-FWD chain', (f) => fwCheck(f.fwd_chain && f.fwd_chain.exists,
                    f.fwd_chain && f.fwd_chain.exists ? `${f.fwd_chain.drop_packets} dropped` : 'missing')],
                ].map(([label, cell]) => (
                  <tr key={label}>
                    <td>{label}</td>
                    {cell(firewall.ipv4)}
                    {cell(firewall.ipv6)}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{fontSize: '12px', color: '#666'}}>
              {firewall ? (firewall.message || 'No firewall detail available.') : 'Checking...'}
            </div>
          )}
        </div>

        {/* Plugable hub: physical sockets, independent power */}
        <div className="debug-section">
          <h2>USB Hub Socket Power{commBadge(hubConnected)}</h2>
          <div style={{marginBottom: '10px', fontSize: '12px', color: '#666'}}>
            Independent per-socket power on the powered hub. Several may be on
            at once &mdash; this is a diagnostic. The Internet page powers only
            one WAN source at a time.
          </div>
          {hubConfigured === false && (
            <div className="error-text" style={{marginBottom: '10px'}}>
              {hubMessage || 'No socket map. Build one with rv/usbhub/map_sockets.py.'}
            </div>
          )}
          <div className="control-grid">
            {Object.entries(hubSockets).map(([label, sock]) => {
              const busy = !!hubBusy[label];
              const ident = (sock.identities || [])
                .map(i => `${i.hub}:${i.port}`).join(' + ');
              const declared = maxWattsDetailed(sock.max_power);
              return (
                <div key={label} className="control-item">
                  <h3>
                    Socket {label}
                    {socketLabel(sock) ? ` \u2014 ${socketLabel(sock)}` : ''}
                  </h3>
                  {/* A switch, not a checkbox. A checkbox reads as "select
                      this socket" when the action is actually powering it on
                      or off; colour plus the word carries that unambiguously.
                      Several sockets can still be on at once -- this is the
                      diagnostic page, and the Internet page is the one that
                      enforces a single WAN. */}
                  <button
                    type="button"
                    className={`power-switch ${sock.enabled ? 'on' : 'off'}`}
                    disabled={busy}
                    aria-pressed={!!sock.enabled}
                    title={`Turn socket ${label} ${sock.enabled ? 'off' : 'on'}`}
                    onClick={() => controlHubSocket(label, !sock.enabled)}
                  >
                    <span className="power-switch-track">
                      <span className="power-switch-knob" />
                    </span>
                    <span className="power-switch-text">
                      {busy ? 'WAIT' : (sock.enabled ? 'ON' : 'OFF')}
                    </span>
                  </button>
                  {/* Watts, per the owner's "show all power in watts", with the
                      raw sysfs mA kept in parentheses: this is the diagnostic
                      page, and the mA figure is what lsusb and the journal
                      print, so it is what you compare against. The conversion
                      is the same helper the Internet page uses. */}
                  <div style={{fontSize: '12px', color: '#666', marginTop: '4px'}}>
                    {sock.device_present
                      ? `${sock.product || 'device'}${declared ? ' \u2014 ' + declared : ''}`
                      : 'empty'}
                  </div>
                  {/* Every sysfs identity the socket has. A USB 3 hub is two
                      hub chips, so a socket can have one port number per
                      speed -- but Sophie's hub lives in a USB 2 port by
                      choice, so the USB 3 chip never enumerates and there is
                      one identity each. Shown because it is what the journal
                      and uhubctl name, and the names change with the Pi port
                      the hub is in. */}
                  <div style={{fontSize: '11px', color: '#999'}}>{ident}</div>
                  {sock.error && <div className="error-text">{sock.error}</div>}
                </div>
              );
            })}
          </div>
          {hubMessage && hubConfigured !== false && (
            <div style={{marginTop: '10px', fontSize: '12px', color: '#666'}}>
              {hubMessage}
            </div>
          )}
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
          <div style={{ marginBottom: '15px', fontWeight: 'bold' }}>
            Current state: {synologyStatus ? ({ ONLINE: 'On', STANDBY: 'Standby (WoL-ready)', OFFLINE: 'Off (no ethernet link)' }[synologyStatus.state] || synologyStatus.state || 'Unknown') : 'Checking...'}
          </div>
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
                <button 
                  className="action-button power-off-button"
                  onClick={synologyFullOff}
                >
                  Full Off (cut power)
                </button>
              </div>
            </div>
          </div>
        </div>

        <SecurityCard />

        {/* System: destructive actions, kept at the bottom and behind a
            confirmation. A reboot drops every WiFi client on Sophie. */}
        <div className="debug-section">
          <h2>System</h2>
          <div className="control-grid">
            <div className="control-item">
              <h3>Restart Program</h3>
              <div style={{fontSize: '12px', color: '#666', marginBottom: '12px'}}>
                Restarts all nine containers. The dashboard goes away for a few
                seconds and comes back; the Pi itself stays up, so WiFi clients
                and the uplink are untouched.
              </div>
              <button className="control-btn" disabled={restarting}
                      onClick={doRestartContainers}>
                {restarting ? 'Restarting\u2026' : 'Restart Program'}
              </button>
            </div>
            <div className="control-item">
              <h3>Reboot</h3>
              <div style={{fontSize: '12px', color: '#666', marginBottom: '12px'}}>
                Reboots the Pi. Every WiFi client on the RV loses its
                connection, including this browser, and the uplink is
                re-selected from scratch on the way back up.
              </div>
              {confirmReboot ? (
                <div className="control-buttons">
                  <button className="control-btn danger" onClick={doReboot}>
                    Yes, reboot
                  </button>
                  <button className="control-btn" onClick={() => setConfirmReboot(false)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  className="control-btn danger"
                  disabled={rebooting}
                  onClick={() => setConfirmReboot(true)}
                >
                  {rebooting ? 'Rebooting\u2026' : 'Reboot Pi'}
                </button>
              )}
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
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                Triggered Errors ({watcherErrors.length})
                <button
                  onClick={() => setWatcherErrors([])}
                  style={{
                    fontSize: '12px', fontWeight: 'normal', padding: '2px 10px',
                    border: '1px solid #ccc', borderRadius: '4px',
                    cursor: 'pointer', background: '#f5f5f5',
                  }}
                >
                  Clear
                </button>
              </h3>
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

/**
 * The panel is gated here rather than inside its own render, so none of its
 * data fetching starts until the device is trusted. The server refuses those
 * endpoints anyway (see _PROTECTED in server.py) -- this only avoids a page
 * full of 401s, and is a convenience, not the control.
 */
function Debug() {
  return (
    <PinGate reason="The debug page can reboot Sophie, cut power to the NAS and switch hub sockets.">
      <DebugPanel />
    </PinGate>
  );
}

export default Debug;
