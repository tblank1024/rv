/**
 * RV Internet Connection Management Page
 *
 * === THE MODEL ===
 * WAN sources live on the Plugable powered hub, one physical socket each, and
 * are selected BY ROLE rather than by port number: the user picks "starlink",
 * not "socket 4". Roles come from /etc/usbhub/sockets.json. Exactly one roled
 * socket is powered at a time, which is the power-saving goal -- several
 * uplinks may be *considered*, only one is left drawing current.
 *
 * Sockets WITHOUT a role are never touched by a switch here. That is what
 * stops a WAN change from cutting the Bluetooth adapter in socket 7, and it is
 * also why socket 1 (the WiFi adapter) has a display *name* but no role.
 *
 * === ONE BUTTON PER OPTION (rewritten 2026-10-26) ===
 * This page used to be radio buttons for the hub plus a separate card of Kasa
 * outlets, which left the user to know that Starlink needs its mains supply on
 * as well as its socket. It is now a plain selector: each option names
 * everything it needs, and POST /api/internet/select applies the socket AND
 * the mains in one call, switching off the accessories the chosen option does
 * not need. The server owns that ordering -- see INTERNET_OPTIONS in
 * server.py -- because getting it wrong cuts power to the uplink being
 * selected.
 *
 * === WHAT THIS PAGE DOES NOT DO ===
 * Powering a socket OFFERS an uplink; it does not seize the default route.
 * pi5connect.sh decides that on the interface event which follows. So the
 * status line reports the route the system actually chose, which can
 * legitimately differ from the option selected above.
 *
 * === WIFI ===
 * Rendered by WifiPicker.jsx, always. The adapter is in socket 1 and keeps no
 * WAN role, so it stays powered whatever is selected -- deliberately: gating
 * the picker behind a WAN selection meant reaching it required dropping the
 * live WAN.
 * NOTE: the route /wifi belongs to the Plex page, not to any of this.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Message, Card, Header, Icon, Button, Label } from 'semantic-ui-react';
import './Internet.css';
import { fetchFromServer } from '../utils/api';
import { maxWatts } from '../utils/power';
import WifiPicker from './WifiPicker';

// The selector, in the order it is shown. `option` is the key POSTed to
// /api/internet/select; `role` is the hub WAN role it needs present, or null
// for the options that need no roled socket. Kept in step with
// INTERNET_OPTIONS in server.py, which owns what each one actually does.
const OPTIONS = [
  { option: 'wired',    role: 'wired',    name: 'Wired' },
  { option: 'wifi',     role: null,       name: 'WiFi' },
  { option: 'cell',     role: 'cell',     name: 'Cellular' },
  { option: 'cell-amp', role: 'cell',     name: 'Cellular + amplifier' },
  { option: 'starlink', role: 'starlink', name: 'Starlink' },
  { option: 'none',     role: null,       name: 'All off' },
];

// What the server reports as the live connection, mapped onto an option key.
const STATE_TO_OPTION = {
  wired: 'wired',
  wifi: 'wifi',
  cellular: 'cell',
  'cellular-amp': 'cell-amp',
  starlink: 'starlink',
  none: 'none',
};

const Internet = () => {
  const [candidates, setCandidates] = useState([]);
  const [configured, setConfigured] = useState(null);
  const [hubMessage, setHubMessage] = useState('');
  const [poweredPresent, setPoweredPresent] = useState([]);

  const [activeOption, setActiveOption] = useState(null);  // null until read
  const [wanInterface, setWanInterface] = useState(null);
  // A choice still being honoured, and the reason one was not. Without these
  // the page would show Wired as active seconds after you picked Cellular,
  // with no indication that failover had overridden you.
  const [manualChoice, setManualChoice] = useState(null);
  const [manualFallback, setManualFallback] = useState(null);

  const [busy, setBusy] = useState('');       // the option being applied
  const [result, setResult] = useState(null); // {ok, message}

  const [wifiSsid, setWifiSsid] = useState('');
  const [wifiDbm, setWifiDbm] = useState(null);
  const [ampWatts, setAmpWatts] = useState(null);
  const [starlinkWatts, setStarlinkWatts] = useState(null);

  const [scanRunning, setScanRunning] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [scanMessage, setScanMessage] = useState('');

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const loadHub = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/hub/wan');
      if (data && data.success) {
        setCandidates(data.candidates || []);
        setPoweredPresent(data.powered_present || []);
        setConfigured(!!data.configured);
        setHubMessage(data.message || '');
      } else {
        setConfigured(false);
        setHubMessage((data && data.message) || 'Hub API unavailable');
      }
    } catch (error) {
      setConfigured(false);
      setHubMessage('Could not reach the hub API: ' + error.message);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/internet/status');
      setWanInterface(data.wan_interface || '');
      setActiveOption(STATE_TO_OPTION[data.current_connection] || null);
      setManualChoice(data.manual_choice || null);
      setManualFallback(data.manual_fallback || null);
    } catch (error) {
      setWanInterface('');
      setActiveOption(null);
    }
  }, []);

  const loadAccessoryPower = useCallback(async () => {
    try {
      const amp = await fetchFromServer('/api/kasa/power/1');
      setAmpWatts(amp && amp.success ? amp.power : null);
      const star = await fetchFromServer('/api/kasa/power/6');
      setStarlinkWatts(star && star.success ? star.power : null);
    } catch (error) {
      // A missing power strip must not blank the selector.
      console.error('Kasa power read failed:', error);
    }
  }, []);

  const loadWifi = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/wifi/status');
      const wifi = (data && data.wifi) || {};
      setWifiSsid(wifi.state === 'connected' ? (wifi.ssid || '') : '');
      setWifiDbm(wifi.signal_dbm != null ? wifi.signal_dbm : null);
    } catch (error) {
      setWifiSsid('');
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadHub(), loadStatus(), loadAccessoryPower(), loadWifi()]);
  }, [loadHub, loadStatus, loadAccessoryPower, loadWifi]);

  const select = async (option) => {
    setBusy(option);
    setResult(null);
    try {
      const data = await fetchFromServer('/api/internet/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ option }),
      });
      setResult({ ok: !!(data && data.success), message: (data && data.message) || '' });
    } catch (error) {
      setResult({ ok: false, message: 'Switch failed: ' + error.message });
    } finally {
      await refreshAll();
      setBusy('');
    }
  };

  // ---- on-demand scan ----------------------------------------------------
  // Deliberately manual. Keeping every adapter powered so a better uplink
  // could be noticed automatically would cost standby current continuously,
  // which defeats powering one WAN at a time. A button costs nothing until
  // pressed.
  const loadScanStatus = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/hub/wan/scan');
      if (data && data.success) {
        setScanRunning(!!data.running);
        if (data.outcome) {
          setScanResult({ outcome: data.outcome, interface: data.interface, socket: data.socket });
        }
        return !!data.running;
      }
    } catch (error) {
      console.error('Scan status failed:', error);
    }
    return false;
  }, []);

  const startScan = async () => {
    setScanMessage('');
    setScanResult(null);
    try {
      const data = await fetchFromServer('/api/hub/wan/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      setScanMessage((data && data.message) || '');
      if (data && data.success) setScanRunning(true);
    } catch (error) {
      setScanMessage('Could not start the scan: ' + error.message);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const data = await fetchFromServer('/api/internet/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connection_type: activeOption || 'wired' }),
      });
      setTestResult({
        connected: !!(data && data.connected),
        message: (data && data.message) || '',
      });
    } catch (error) {
      setTestResult({ connected: false, message: error.message });
    } finally {
      await loadStatus();
      setTesting(false);
    }
  };

  useEffect(() => { refreshAll(); loadScanStatus(); }, [refreshAll, loadScanStatus]);

  // Poll only while a scan is in flight: a cold cellular test takes ~60s.
  useEffect(() => {
    if (!scanRunning) return undefined;
    const timer = setInterval(async () => {
      const running = await loadScanStatus();
      if (!running) await refreshAll();
    }, 5000);
    return () => clearInterval(timer);
  }, [scanRunning, loadScanStatus, refreshAll]);

  const candidateFor = (role) => candidates.find((c) => c.role === role);

  /**
   * The one-line explanation under an option's name, and whether it can be
   * picked. A GATED socket reports present=false only because it is powered
   * down on purpose -- picking it is what powers it up -- while an EMPTY
   * socket enumerates nothing and must stay unpickable. Treating the two
   * alike made cellular unselectable the moment gating was switched on.
   */
  const describe = (spec) => {
    if (spec.option === 'wifi') {
      const where = wifiSsid
        ? `connected to ${wifiSsid}${wifiDbm != null ? ` · ${wifiDbm} dBm` : ''}`
        : 'adapter powered, not associated';
      return { detail: `${where} · stays powered whatever is selected`, disabled: false };
    }
    if (spec.option === 'none') {
      return {
        detail: 'Switched uplinks and accessories off. The WiFi adapter stays '
              + 'powered and may reassociate on its own.',
        disabled: false,
      };
    }

    const cand = candidateFor(spec.role);
    if (!cand) {
      return { detail: `no socket has the "${spec.role}" role`, disabled: true };
    }
    const bits = [`socket ${cand.socket}`];
    if (cand.present) {
      bits.push(cand.product || 'device');
      const watts = maxWatts(cand.max_power);
      if (watts) bits.push(watts);
    } else if (cand.gated) {
      bits.push('powered only while selected');
    } else {
      bits.push('nothing plugged in');
    }
    if (spec.option === 'cell-amp') {
      bits.push(ampWatts != null ? `amplifier ${ampWatts} W` : 'amplifier mains on');
    }
    if (spec.option === 'starlink') {
      bits.push(starlinkWatts != null ? `supply ${starlinkWatts} W` : 'supply mains on');
    }
    return {
      detail: bits.join(' · '),
      disabled: !cand.present && !cand.gated,
    };
  };

  return (
    <div className="internet-page">
      <div className="internet-container">
        <Header as="h1" icon textAlign="center">
          <Icon name="wifi" />
          <Header.Content>
            Internet Connection
            <Header.Subheader>Pick how Sophie gets online</Header.Subheader>
          </Header.Content>
        </Header>

        {/* ---- the selector ---------------------------------------------- */}
        <Card className="internet-control-card" fluid>
          <Card.Content>
            <Card.Header>Options</Card.Header>

            {configured === false && (
              <Message warning size="small" style={{ marginTop: '10px' }}>
                {hubMessage || 'No socket map yet. Build one with rv/usbhub/map_sockets.py.'}
              </Message>
            )}

            <div className="wan-options">
              {OPTIONS.map((spec) => {
                const { detail, disabled } = describe(spec);
                const active = activeOption === spec.option;
                return (
                  <button
                    key={spec.option}
                    type="button"
                    className={`wan-option${active ? ' wan-option--active' : ''}`}
                    disabled={disabled || !!busy}
                    onClick={() => select(spec.option)}
                  >
                    <span className="wan-option__mark">
                      {busy === spec.option
                        ? <Icon name="circle notched" loading />
                        : active ? <Icon name="check circle" color="green" /> : null}
                    </span>
                    <span className="wan-option__text">
                      <span className="wan-option__name">{spec.name}</span>
                      <span className="wan-option__detail">{detail}</span>
                    </span>
                    {active && <Label size="mini" color="green">Active</Label>}
                  </button>
                );
              })}
            </div>

            {busy && (
              <div style={{ marginTop: '10px' }}>
                <Icon name="circle notched" loading /> Switching — a socket
                change is a USB control transfer per device and takes seconds.
              </div>
            )}

            {result && (
              <Message size="small" positive={result.ok} negative={!result.ok}
                       style={{ marginTop: '10px' }}
                       onDismiss={() => setResult(null)}>
                {result.message}
              </Message>
            )}

            {/* More than one powered means exclusivity has never been applied
                -- the state the hub is in after a fresh socket map. */}
            {!busy && poweredPresent.length > 1 && (
              <Message warning size="small" style={{ marginTop: '10px' }}>
                {poweredPresent.length} uplinks are powered at once
                ({poweredPresent.join(', ')}). Pick one above to apply exclusivity.
              </Message>
            )}

            {manualFallback && (
              <Message warning size="small" style={{ marginTop: '10px' }}>
                You picked <strong>{manualFallback.wanted}</strong>, but it did
                not come up, so the system fell back to{' '}
                <strong>{manualFallback.got}</strong> rather than leave the RV
                offline. Pick it again to retry.
              </Message>
            )}

            {manualChoice && (
              <Message info size="small" style={{ marginTop: '10px' }}>
                <strong>{manualChoice.role}</strong> was chosen deliberately, so
                automatic failover will not move off it while it is working.
              </Message>
            )}

            <div className="wan-status-line">
              <span>
                <strong>Default route: </strong>
                {wanInterface === null ? (
                  <><Icon name="circle notched" loading /> reading…</>
                ) : wanInterface ? (
                  <><Icon name="check circle" color="green" />
                    <Label basic size="small">{wanInterface}</Label></>
                ) : (
                  <><Icon name="times circle" color="red" /> none</>
                )}
              </span>
              <span>
                <Button size="small" onClick={runTest} loading={testing} disabled={testing}>
                  <Icon name="exchange" /> Test
                </Button>
                <Button size="small" onClick={startScan}
                        loading={scanRunning} disabled={scanRunning || !!busy}>
                  <Icon name="search" /> Find best
                </Button>
              </span>
            </div>

            {wanInterface === '' && (
              <Message negative size="small" style={{ marginTop: '10px' }}>
                No default route. The RV has no internet; the LAN and SSH over
                br0 are unaffected.
              </Message>
            )}

            {testResult && (
              <Message size="small" positive={testResult.connected}
                       negative={!testResult.connected} style={{ marginTop: '10px' }}>
                {testResult.message || (testResult.connected ? 'Reachable' : 'Not reachable')}
              </Message>
            )}

            {scanMessage && (
              <Message size="small" info style={{ marginTop: '8px' }}>{scanMessage}</Message>
            )}
            {!scanRunning && scanResult && (
              <Message size="small" positive={scanResult.outcome === 'ok'}
                       style={{ marginTop: '8px' }}>
                {scanResult.outcome === 'ok'
                  ? `Settled on ${scanResult.interface} (socket ${scanResult.socket}).`
                  : scanResult.outcome === 'nochange'
                    ? 'Nothing better found; the current uplink was left alone.'
                    : `Scan reported: ${scanResult.outcome}`}
              </Message>
            )}
          </Card.Content>
        </Card>

        {/* ---- WiFi networks --------------------------------------------- */}
        <div style={{ marginTop: '20px', marginBottom: '20px' }}>
          <WifiPicker onConnected={refreshAll} />
        </div>
      </div>
    </div>
  );
};

export default Internet;
