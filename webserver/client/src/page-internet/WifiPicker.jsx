/**
 * WifiPicker — a conventional WiFi picker for the Pi Zero 2W uplink.
 *
 * Replaces a blind SSID + password form. Shows what is in range with signal
 * strength, connects on tap, and asks for a password only when the Zero has no
 * saved credential for that network.
 *
 * Talks to /api/wifi/* on the RP5, which proxies the JSON service running as
 * root on the Zero (scanning requires root there).
 *
 * Things that drive the design, all of them measured on the real hardware:
 *  - Profile name is NOT the SSID and is not unique, so a Forget confirmation
 *    must name the profile it will delete, and every action keys on uuid.
 *  - A connect returns immediately with a job id; progress arrives through
 *    /api/wifi/status as operation.state. Polling is the only way to see the
 *    outcome, so the status panel is the source of truth, not the click.
 *  - The RV's own AP ("Sophie") is visible to the Zero. Joining it would loop
 *    the uplink back through the RP5. It is shown, disabled, with the reason.
 *  - The column is capped at 400px, so rows are tap-to-expand rather than
 *    carrying inline buttons.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Button, Card, Icon, Message, Modal, Form, Segment, TextArea } from 'semantic-ui-react';
import { fetchFromServer } from '../utils/api';

const STATUS_POLL_IDLE = 5000;     // ms; the Zero caches status for 1s
const STATUS_POLL_BUSY = 2000;     // while a connect/forget is running
const STATUS_POLL_BACKOFF = 15000; // after repeated unreachable errors
const RESCAN_COOLDOWN = 10000;     // mirrors the Zero's own rescan floor
const MAX_LOG_LINES = 200;

const stamp = () => new Date().toLocaleTimeString();

/** 0-100 signal as four bars. Semantic's wifi icon has no strength variants. */
const SignalBars = ({ signal }) => {
  const filled = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : signal > 0 ? 1 : 0;
  return (
    <span className="wifi-bars" title={`${signal}%`} aria-label={`signal ${signal}%`}>
      {[1, 2, 3, 4].map((n) => (
        <span key={n} className={`wifi-bar ${n <= filled ? 'wifi-bar--on' : 'wifi-bar--off'}`} />
      ))}
    </span>
  );
};

const WifiPicker = () => {
  const [networks, setNetworks] = useState([]);
  const [scanAge, setScanAge] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState('');
  const [lastScanAt, setLastScanAt] = useState(0);

  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState('');

  const [expanded, setExpanded] = useState('');     // ssid of the open row
  const [pending, setPending] = useState('');       // ssid being connected
  const [result, setResult] = useState(null);       // {type, message}

  const [pwFor, setPwFor] = useState(null);         // network awaiting a password
  const [pwValue, setPwValue] = useState('');
  const [pwShow, setPwShow] = useState(false);

  const [forgetFor, setForgetFor] = useState(null);
  const [showLog, setShowLog] = useState(false);
  const [log, setLog] = useState('');

  // Refs so the poller can read current values without re-subscribing.
  const failuresRef = useRef(0);
  const pendingRef = useRef('');
  const lastOpRef = useRef('');
  pendingRef.current = pending;

  const addLog = useCallback((line) => {
    setLog((prev) => {
      const next = `${stamp()}  ${line}\n${prev}`;
      return next.split('\n').slice(0, MAX_LOG_LINES).join('\n');
    });
  }, []);

  const loadNetworks = useCallback(async (rescan) => {
    if (rescan) setScanning(true);
    try {
      const data = await fetchFromServer(`/api/wifi/networks?rescan=${rescan ? 1 : 0}`);
      if (!data.success) {
        setScanError(data.message || 'Could not scan');
        addLog(`Scan failed: ${data.message || data.error}`);
        return;
      }
      setNetworks(data.networks || []);
      setScanAge(data.age_seconds);
      setScanError('');
      if (rescan) {
        setLastScanAt(Date.now());
        addLog(`Scanned — ${(data.networks || []).length} networks`);
      }
    } catch (err) {
      setScanError(err.message);
      addLog(`Scan failed: ${err.message}`);
    } finally {
      if (rescan) setScanning(false);
    }
  }, [addLog]);

  const loadProfilesAndNetworks = useCallback(async () => {
    // A forget changes `saved` on rows, so the list has to come back.
    await loadNetworks(false);
  }, [loadNetworks]);

  /** Status poll. Silent: it must not churn spinners or messages. */
  const pollStatus = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/wifi/status');
      if (!data.success) {
        failuresRef.current += 1;
        setStatusError(data.message || 'The WiFi bridge is not responding');
        return;
      }
      failuresRef.current = 0;
      setStatusError('');
      setStatus(data);

      const op = data.operation || {};
      // Report an operation's outcome once, when it transitions.
      const key = `${op.id}:${op.state}`;
      if (op.id && key !== lastOpRef.current &&
          (op.state === 'succeeded' || op.state === 'failed')) {
        lastOpRef.current = key;
        setPending('');
        if (op.state === 'succeeded') {
          const ip = (data.wifi && data.wifi.ip) || '';
          setResult({ type: 'success', message: `Connected to ${op.ssid}${ip ? ` — ${ip}` : ''}` });
          addLog(`Connected to ${op.ssid}${ip ? ` — ${ip}` : ''}`);
        } else {
          const rolled = op.rolled_back ? ' Previous network restored.' : '';
          setResult({ type: 'error', message: `${op.ssid}: ${op.error || 'failed'}.${rolled}` });
          addLog(`Failed: ${op.ssid}: ${op.error || 'failed'}${rolled}`);
        }
        loadProfilesAndNetworks();
      } else if (op.state === 'running' && op.phase) {
        setPending(op.ssid);
      }
    } catch (err) {
      failuresRef.current += 1;
      setStatusError(err.message);
    }
  }, [addLog, loadProfilesAndNetworks]);

  // Scan once on mount; never on a timer, since a rescan while
  // NetworkManager is associating fights the association.
  useEffect(() => {
    loadNetworks(true);
    pollStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Status polling, paced by whether something is running, backed off when the
  // bridge is unreachable, and stopped while the tab is hidden (this runs on
  // an always-on dashboard tablet).
  useEffect(() => {
    let timer = null;
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      if (!document.hidden) await pollStatus();
      if (stopped) return;
      const delay = failuresRef.current >= 3 ? STATUS_POLL_BACKOFF
        : pendingRef.current ? STATUS_POLL_BUSY : STATUS_POLL_IDLE;
      timer = setTimeout(tick, delay);
    };
    timer = setTimeout(tick, STATUS_POLL_IDLE);
    const onVisible = () => { if (!document.hidden) pollStatus(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [pollStatus]);

  const connect = useCallback(async (ssid, psk) => {
    setPending(ssid);
    setResult(null);
    setExpanded('');
    addLog(`Connecting to ${ssid}…`);
    try {
      const data = await fetchFromServer('/api/wifi/connect', {
        method: 'POST',
        body: JSON.stringify(psk ? { ssid, psk } : { ssid }),
      });
      if (!data.success) {
        setPending('');
        setResult({ type: 'error', message: data.message || 'Could not start connecting' });
        addLog(`Rejected: ${data.message || data.error}`);
      }
      // Success path is reported by the status poller, not here.
    } catch (err) {
      setPending('');
      setResult({ type: 'error', message: err.message });
      addLog(`Connect failed: ${err.message}`);
    }
  }, [addLog]);

  const onRowClick = (network) => {
    if (!network.joinable || pending) return;
    if (network.saved && network.has_psk) {
      // Known network: just connect. Tapping an already-connected row expands
      // instead, so Forget stays reachable.
      if (network.in_use) {
        setExpanded(expanded === network.ssid ? '' : network.ssid);
      } else {
        connect(network.ssid, '');
      }
      return;
    }
    if (network.saved) {
      setExpanded(expanded === network.ssid ? '' : network.ssid);
      return;
    }
    setPwFor(network);
    setPwValue('');
    setPwShow(false);
  };

  const submitPassword = () => {
    const network = pwFor;
    setPwFor(null);
    connect(network.ssid, pwValue);
    setPwValue('');
  };

  const doForget = async () => {
    const target = forgetFor;
    setForgetFor(null);
    try {
      const data = await fetchFromServer('/api/wifi/forget', {
        method: 'POST',
        body: JSON.stringify({ uuid: target.profile_uuid, force: !!target.in_use }),
      });
      if (!data.success) {
        setResult({ type: 'error', message: data.message || 'Could not forget that network' });
        addLog(`Forget failed: ${data.message || data.error}`);
      } else {
        setResult({ type: 'success', message: `Forgot ${data.deleted?.name || target.ssid}` });
        addLog(`Forgot profile ${data.deleted?.name || target.ssid}`);
      }
    } catch (err) {
      setResult({ type: 'error', message: err.message });
      addLog(`Forget failed: ${err.message}`);
    }
    setExpanded('');
    loadProfilesAndNetworks();
  };

  const wifi = (status && status.wifi) || {};
  const op = (status && status.operation) || {};
  const cooling = Date.now() - lastScanAt < RESCAN_COOLDOWN;
  // The status endpoint's signal comes from the Zero's scan cache and reads 0
  // before the first scan; prefer the in-use row when we have it.
  const liveRow = networks.find((n) => n.in_use);
  const liveSignal = wifi.signal || (liveRow ? liveRow.signal : 0);

  return (
    <div className="wifi-picker">
      <Card className="wifi-status-card">
        <Card.Content>
          <Card.Header>
            WiFi bridge
            {op.state === 'running' && <Icon name="circle notched" loading style={{ marginLeft: 8 }} />}
          </Card.Header>
        </Card.Content>
        <Card.Content>
          {statusError ? (
            <Message negative size="small" icon="plug">
              <Message.Content>
                <Message.Header>Bridge not responding</Message.Header>
                {statusError}
              </Message.Content>
            </Message>
          ) : (
            <div className="wifi-status-grid">
              <div className="wifi-status-row">
                <strong>State</strong>
                <span>
                  {op.state === 'running'
                    ? `${op.phase || 'working'}…`
                    : (wifi.state || 'unknown')}
                </span>
              </div>
              <div className="wifi-status-row">
                <strong>Network</strong>
                <span>{wifi.ssid || '—'}</span>
              </div>
              <div className="wifi-status-row">
                <strong>Signal</strong>
                <span>{liveSignal ? <><SignalBars signal={liveSignal} /> {liveSignal}%</> : '—'}</span>
              </div>
              <div className="wifi-status-row">
                <strong>Address</strong>
                <span>{wifi.ip || '—'}</span>
              </div>
              <div className="wifi-status-row">
                <strong>Profile</strong>
                <span>{wifi.profile || '—'}</span>
              </div>
            </div>
          )}
        </Card.Content>
      </Card>

      <Card className="wifi-config-card" style={{ marginTop: '15px' }}>
        <Card.Content>
          <Card.Header>
            Available networks
            <Button
              floated="right"
              size="mini"
              icon="refresh"
              content="Rescan"
              loading={scanning}
              disabled={scanning || cooling || !!pending}
              onClick={() => loadNetworks(true)}
            />
          </Card.Header>
          <Card.Description className="wifi-scan-age">
            {scanning ? 'Scanning…'
              : scanAge == null ? ''
              : scanAge < 2 ? 'Updated just now'
              : `Updated ${Math.round(scanAge)}s ago`}
          </Card.Description>
        </Card.Content>
        <Card.Content>
          {scanError && <Message negative size="small" content={scanError} />}
          {!scanError && networks.length === 0 && !scanning && (
            <div className="wifi-empty">No networks found. Try Rescan.</div>
          )}
          <div className="wifi-list">
            {networks.map((network) => {
              const isPending = pending === network.ssid;
              const isOpen = expanded === network.ssid;
              const classes = ['wifi-row'];
              if (network.in_use) classes.push('wifi-row--active');
              if (!network.joinable) classes.push('wifi-row--blocked');
              if (isPending) classes.push('wifi-row--pending');
              if (isOpen) classes.push('wifi-row--expanded');
              return (
                <div key={network.ssid}>
                  <button
                    type="button"
                    className={classes.join(' ')}
                    onClick={() => onRowClick(network)}
                    disabled={!network.joinable || (!!pending && !isPending)}
                    aria-disabled={!network.joinable}
                    title={network.unjoinable_reason || network.ssid}
                  >
                    <SignalBars signal={network.signal} />
                    <span className="wifi-row__name">
                      {network.ssid}
                      {!network.joinable && network.unjoinable_reason
                        && <span className="wifi-row__why"> ({network.unjoinable_reason})</span>}
                    </span>
                    <span className="wifi-row__tags">
                      {network.in_use && <span className="wifi-tag wifi-tag--connected">Connected</span>}
                      {!network.in_use && network.saved && <span className="wifi-tag wifi-tag--saved">Saved</span>}
                      {!network.security && <span className="wifi-tag wifi-tag--open">Open</span>}
                      {network.security && <Icon name="lock" size="small" className="wifi-row__lock" />}
                      {isPending && <Icon name="circle notched" loading />}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="wifi-actions">
                      {!network.in_use && (
                        <Button size="mini" primary icon="sign-in" content="Connect"
                                disabled={!!pending}
                                onClick={() => connect(network.ssid, '')} />
                      )}
                      {network.saved && (
                        <Button size="mini" icon="key" content="New password"
                                disabled={!!pending}
                                onClick={() => { setPwFor(network); setPwValue(''); setExpanded(''); }} />
                      )}
                      {network.saved && (
                        <Button size="mini" negative basic icon="trash" content="Forget"
                                disabled={!!pending}
                                onClick={() => setForgetFor(network)} />
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card.Content>
      </Card>

      {result && (
        <Message
          style={{ marginTop: '15px' }}
          color={result.type === 'success' ? 'green' : result.type === 'warning' ? 'yellow' : 'red'}
          icon={result.type === 'success' ? 'check circle' : result.type === 'warning' ? 'warning circle' : 'times circle'}
          header={result.type === 'success' ? 'Success' : result.type === 'warning' ? 'Warning' : 'Error'}
          content={result.message}
          onDismiss={() => setResult(null)}
        />
      )}

      <div className="wifi-log-toggle">
        <Button basic size="mini" onClick={() => setShowLog(!showLog)}
                icon={showLog ? 'chevron down' : 'chevron right'}
                content="Activity log" />
        {showLog && (
          <Button basic size="mini" icon="trash" content="Clear" onClick={() => setLog('')} />
        )}
      </div>
      {showLog && (
        <Card className="wifi-output-card">
          <Card.Content>
            <Segment className="output-segment">
              <TextArea value={log} readOnly className="wifi-log"
                        placeholder="Scans, connections and failures appear here…"
                        style={{ width: '100%', minHeight: '120px' }} />
            </Segment>
          </Card.Content>
        </Card>
      )}

      <Modal open={!!pwFor} onClose={() => setPwFor(null)} size="small" closeIcon
             className="wifi-modal">
        <Modal.Header>{pwFor ? `Connect to "${pwFor.ssid}"` : ''}</Modal.Header>
        <Modal.Content>
          {pwFor && pwFor.saved && (
            <Message warning size="small" icon="exclamation triangle">
              <Message.Content>
                This replaces the saved password for profile
                {' '}<strong>{pwFor.profile || pwFor.ssid}</strong>. The old one cannot be recovered.
              </Message.Content>
            </Message>
          )}
          <Form onSubmit={(e) => { e.preventDefault(); if (pwValue.length >= 8) submitPassword(); }}>
            <Form.Field>
              <label>Password</label>
              <Form.Input
                type={pwShow ? 'text' : 'password'}
                value={pwValue}
                autoComplete="off"
                autoFocus
                placeholder="8 to 63 characters"
                onChange={(e) => setPwValue(e.target.value)}
                action={{
                  icon: pwShow ? 'eye slash' : 'eye',
                  type: 'button',
                  onClick: () => setPwShow(!pwShow),
                }}
              />
            </Form.Field>
            <div className="wifi-pw-hint">
              {pwValue.length === 0 ? 'WPA networks need 8 to 63 characters.'
                : pwValue.length < 8 ? `${8 - pwValue.length} more character(s) needed.`
                : pwValue.length > 63 ? 'Too long — 63 characters maximum.'
                : ' '}
            </div>
          </Form>
        </Modal.Content>
        <Modal.Actions>
          <Button onClick={() => setPwFor(null)} content="Cancel" />
          <Button primary icon="sign-in" labelPosition="left" content="Connect"
                  disabled={pwValue.length < 8 || pwValue.length > 63}
                  onClick={submitPassword} />
        </Modal.Actions>
      </Modal>

      <Modal open={!!forgetFor} onClose={() => setForgetFor(null)} size="small" closeIcon
             className="wifi-modal">
        <Modal.Header>{forgetFor ? `Forget "${forgetFor.ssid}"?` : ''}</Modal.Header>
        <Modal.Content>
          {forgetFor && (
            <>
              <p>
                This deletes the saved profile{' '}
                <strong>{forgetFor.profile || forgetFor.ssid}</strong> and its password.
              </p>
              {forgetFor.profile_count > 1 && (
                <Message info size="small">
                  {forgetFor.ssid} has {forgetFor.profile_count} saved profiles; only{' '}
                  <strong>{forgetFor.profile}</strong> will be deleted.
                </Message>
              )}
              {forgetFor.in_use && (
                <Message negative size="small" icon="warning sign">
                  <Message.Content>
                    <Message.Header>This is the network providing internet</Message.Header>
                    Forgetting it will disconnect the RV until another network is joined.
                  </Message.Content>
                </Message>
              )}
            </>
          )}
        </Modal.Content>
        <Modal.Actions>
          <Button onClick={() => setForgetFor(null)} content="Cancel" />
          <Button negative icon="trash" labelPosition="left" onClick={doForget}
                  content={forgetFor && forgetFor.in_use ? 'Disconnect and forget' : 'Forget'} />
        </Modal.Actions>
      </Modal>
    </div>
  );
};

export default WifiPicker;
