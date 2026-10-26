/**
 * PinPrompt / PinGate — the dashboard's PIN entry.
 *
 * Design, scope and the measurements behind it: plan_pin_protection.md.
 *
 * What this is NOT: authentication. The dashboard is plain HTTP, so the PIN
 * crosses the air in clear text, and anything on the RV LAN that is not a
 * browser can still reach whatever the server does not gate. The server is
 * what enforces this (see _PROTECTED in server.py); PinGate only stops the
 * page rendering, which is a convenience, not a control. Hiding a button
 * while leaving its endpoint open would be theatre.
 *
 * It is sized for the threat that actually exists: a guest with Sophie's WiFi
 * password, or somebody tapping Reboot to see what it does.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Button, Card, Icon, Message, Form } from 'semantic-ui-react';
import { fetchFromServer, getServerUrl } from '../utils/api';
import './PinPrompt.css';

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫'];

/** POST that needs the raw status code, which fetchFromServer hides. */
const post = async (path, body) => {
  const response = await fetch(`${getServerUrl()}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await response.json(); } catch (e) { /* empty body */ }
  return { status: response.status, data };
};

export const PinPrompt = ({ reason, onUnlocked, onCancel, cancelText }) => {
  const [pin, setPin] = useState('');
  const [confirm, setConfirm] = useState('');
  const [status, setStatus] = useState(null);     // from /api/auth/status
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [freeze, setFreeze] = useState(0);        // seconds remaining

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/auth/status');
      setStatus(data);
      setFreeze(data.retry_after || 0);
    } catch (err) {
      // Leaving `status` null here spun on "Checking…" for ever with nothing
      // said, because the spinner is the no-status-yet state. Record the
      // failure as a status of its own so the card can explain itself.
      setStatus({ configured: true, authenticated: false, unreachable: true });
      setError('Could not reach the server: ' + err.message);
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  // Count the freeze down so the wait is visible rather than a dead keypad.
  useEffect(() => {
    if (freeze <= 0) return undefined;
    const timer = setInterval(() => setFreeze((s) => (s > 1 ? s - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [freeze]);

  const settingUp = status && !status.configured;

  const tap = (key) => {
    setError('');
    if (key === '⌫') { setPin((p) => p.slice(0, -1)); return; }
    if (key === '') return;
    setPin((p) => (p.length >= 12 ? p : p + key));
  };

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      if (settingUp) {
        if (pin !== confirm) { setError('The two PINs do not match.'); return; }
        const { data } = await post('/api/auth/setup', { pin });
        if (!data.success) { setError(data.message || 'Could not set the PIN.'); return; }
        onUnlocked();
        return;
      }
      const { status: code, data } = await post('/api/auth/pin', { pin });
      if (data.success) { onUnlocked(); return; }
      setPin('');
      if (code === 429) {
        setFreeze(data.retry_after || 900);
        setError(data.message || 'Too many wrong attempts.');
      } else {
        setError(
          data.attempts_left != null
            ? `Wrong PIN. ${data.attempts_left} attempt${data.attempts_left === 1 ? '' : 's'} left before a 15 minute lockout.`
            : (data.message || 'Wrong PIN.')
        );
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!status) {
    return <Card fluid><Card.Content><Icon name="circle notched" loading /> Checking…</Card.Content></Card>;
  }

  if (status.unreachable) {
    return (
      <Card fluid>
        <Card.Content>
          <Card.Header><Icon name="lock" /> Enter the PIN</Card.Header>
          <Message negative size="small" style={{ marginTop: '10px' }}>
            Cannot reach the server to check whether a PIN is needed, so this
            page stays locked. {error}
          </Message>
          <Button onClick={loadStatus}>Try again</Button>
        </Card.Content>
      </Card>
    );
  }

  // No PIN set and we are not on Sophie's own network: the server refuses to
  // set one from here, so say that rather than offering a form that fails.
  if (settingUp && !status.can_set_pin) {
    return (
      <Card fluid>
        <Card.Content>
          <Card.Header><Icon name="lock" /> No PIN set yet</Card.Header>
          <Message warning size="small" style={{ marginTop: '10px' }}>
            A PIN has not been set, and it can only be set from Sophie&rsquo;s own
            network — not over the campground or house connection you are using.
            Join Sophie&rsquo;s WiFi and reload this page.
          </Message>
        </Card.Content>
      </Card>
    );
  }

  return (
    <Card fluid className="pin-card">
      <Card.Content>
        <Card.Header>
          <Icon name={settingUp ? 'lock open' : 'lock'} />
          {settingUp ? 'Choose a PIN' : 'Enter the PIN'}
        </Card.Header>
        <Card.Meta style={{ marginTop: '6px' }}>
          {settingUp
            ? 'At least 4 digits. It protects reboot, power and turning the alarm '
              + 'off — not the rest of the dashboard. Until you set one, none of '
              + 'those are protected.'
            : (reason || 'This page can reboot Sophie and cut power.')}
        </Card.Meta>

        <div className="pin-display">
          {pin.length === 0
            ? <span className="pin-display__empty">— — — —</span>
            : '•'.repeat(pin.length)}
        </div>

        {settingUp && (
          <Form style={{ marginTop: '10px' }}>
            <Form.Input
              type="password" label="Confirm the PIN" value={confirm}
              inputMode="numeric" autoComplete="off"
              onChange={(e) => setConfirm(e.target.value.replace(/\D/g, ''))}
            />
          </Form>
        )}

        <div className="pin-keypad">
          {KEYS.map((key, i) => (
            <button key={i} type="button" className="pin-key"
                    disabled={!key || busy || freeze > 0}
                    style={{ visibility: key ? 'visible' : 'hidden' }}
                    onClick={() => tap(key)}>
              {key}
            </button>
          ))}
        </div>

        {freeze > 0 && (
          <Message negative size="small">
            Locked out for another {Math.floor(freeze / 60)}m {freeze % 60}s.
          </Message>
        )}
        {error && freeze === 0 && <Message negative size="small">{error}</Message>}

        <div style={{ marginTop: '10px', display: 'flex', gap: '8px' }}>
          <Button primary loading={busy} onClick={submit}
                  disabled={busy || freeze > 0 || pin.length < 4
                            || (settingUp && confirm.length < 4)}>
            {settingUp ? 'Set PIN' : 'Unlock'}
          </Button>
          {onCancel && (
            <Button onClick={onCancel} disabled={busy}>
              {cancelText || 'Cancel'}
            </Button>
          )}
        </div>
      </Card.Content>
    </Card>
  );
};

/**
 * Renders `children` only once this device is trusted.
 *
 * The no-PIN-set case is the subtle one, and the first version got it wrong.
 * The server gates nothing until a PIN exists, so letting the page straight
 * through looked right -- but it meant the setup flow inside PinPrompt existed
 * and nothing could ever reach it, so opening the debug page never offered to
 * set a PIN. Reported 2026-10-26.
 *
 * So: with no PIN set, prompt to choose one, but always with a way past. The
 * owner must never be *unable* to reach the page, since the server is not
 * enforcing anything yet anyway -- a hard block here would be a lockout with
 * no security benefit. Off the RV LAN the server refuses to set a PIN at all,
 * so there is nothing to offer and the page is shown directly.
 */
export const PinGate = ({ children, reason }) => {
  const [state, setState] = useState(null);   // null = still checking
  const [skippedSetup, setSkippedSetup] = useState(false);

  const check = useCallback(async () => {
    try {
      const data = await fetchFromServer('/api/auth/status');
      setState(data);
    } catch (err) {
      // Fail CLOSED. If the status cannot be read we do not know whether a
      // PIN is set, and guessing "no" would hand over the page precisely when
      // something is wrong.
      setState({ configured: true, authenticated: false, unreachable: err.message });
    }
  }, []);

  useEffect(() => { check(); }, [check]);

  const prompt = (node) => (
    <div style={{ maxWidth: '420px', margin: '30px auto', padding: '0 16px' }}>
      {node}
    </div>
  );

  if (state === null) {
    return <div style={{ padding: '20px' }}><Icon name="circle notched" loading /> Checking…</div>;
  }
  if (state.authenticated && state.configured) return children;

  if (!state.configured) {
    // Cannot be set from here, or the owner chose to deal with it later.
    if (!state.can_set_pin || skippedSetup) return children;
    return prompt(
      <PinPrompt reason={reason} onUnlocked={check}
                 onCancel={() => setSkippedSetup(true)}
                 cancelText="Skip for now" />
    );
  }
  return prompt(<PinPrompt reason={reason} onUnlocked={check} />);
};

export default PinGate;
