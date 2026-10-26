/**
 * SecurityCard — change the dashboard PIN, or sign every device out.
 *
 * Added because the endpoints existed but nothing could reach them: once a PIN
 * was set it could only be changed with curl, which on a wall-mounted tablet
 * means not at all. Design and scope: plan_pin_protection.md.
 *
 * Every flow here is keypad-only. The device this runs on has no keyboard, and
 * putting one value of a PIN form in a text field is exactly the mistake that
 * made the original setup dialog impossible to complete.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Button, Icon, Message } from 'semantic-ui-react';
import { fetchFromServer } from '../utils/api';
import { Keypad, PinPrompt, post } from './PinPrompt';
import './PinPrompt.css';

const trustedFor = (seconds) => {
  if (seconds == null) return '';
  const days = Math.floor(seconds / 86400);
  if (days >= 1) return `${days} day${days === 1 ? '' : 's'}`;
  const hours = Math.max(1, Math.round(seconds / 3600));
  return `${hours} hour${hours === 1 ? '' : 's'}`;
};

const SecurityCard = () => {
  const [status, setStatus] = useState(null);
  // 'idle' | 'current' | 'new' | 'confirm' -- the change flow needs three
  // keypad passes, since none of the three values can come from a keyboard.
  const [stage, setStage] = useState('idle');
  const [current, setCurrent] = useState('');
  const [fresh, setFresh] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [confirmForget, setConfirmForget] = useState(false);
  const [settingUp, setSettingUp] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await fetchFromServer('/api/auth/status'));
    } catch (err) {
      setError('Could not read the PIN status: ' + err.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const reset = () => {
    setStage('idle'); setCurrent(''); setFresh(''); setAgain('');
    setError(''); setSettingUp(false);
  };

  const value = stage === 'current' ? current : stage === 'new' ? fresh : again;
  const setValue = (v) => {
    setError('');
    if (stage === 'current') setCurrent(v);
    else if (stage === 'new') setFresh(v);
    else setAgain(v);
  };

  const advance = async () => {
    if (stage === 'current') { setStage('new'); return; }
    if (stage === 'new') { setStage('confirm'); return; }

    if (fresh !== again) {
      // Back to the new-PIN pass with both cleared: re-asking only for the
      // confirmation would let a typo in the first one get saved.
      setError('The new PINs did not match. Enter the new PIN again.');
      setFresh(''); setAgain(''); setStage('new');
      return;
    }
    setBusy(true);
    try {
      const { data } = await post('/api/auth/change', { current, new: fresh });
      if (!data.success) {
        setError(data.message || 'Could not change the PIN.');
        // A wrong CURRENT PIN means starting over; a rejected new one does not.
        setCurrent(''); setFresh(''); setAgain('');
        setStage('current');
        return;
      }
      setNote(data.message || 'PIN changed.');
      reset();
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const forgetAll = async () => {
    setConfirmForget(false);
    setBusy(true);
    try {
      const { data } = await post('/api/auth/revoke-all', {});
      setNote(data.success
        ? 'Every device signed out, including this one. Reload to enter the PIN again.'
        : (data.message || 'Could not sign the devices out.'));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      load();
    }
  };

  if (!status) {
    return (
      <div className="debug-section">
        <h2>Security</h2>
        <div><Icon name="circle notched" loading /> Checking…</div>
      </div>
    );
  }

  return (
    <div className="debug-section">
      <h2>Security</h2>

      {note && <Message positive size="small" onDismiss={() => setNote('')}>{note}</Message>}
      {error && stage === 'idle' && <Message negative size="small">{error}</Message>}

      {!status.configured ? (
        <div className="control-grid">
          <div className="control-item">
            <h3>No PIN set</h3>
            <div style={{ fontSize: '12px', color: '#666', marginBottom: '12px' }}>
              Reboot, power and turning the alarm off are unprotected. Anyone on
              Sophie&rsquo;s WiFi can use them.
            </div>
            {settingUp ? (
              <PinPrompt onUnlocked={() => { setSettingUp(false); load(); }}
                         onCancel={() => setSettingUp(false)} cancelText="Not now" />
            ) : (
              <button className="control-btn" onClick={() => setSettingUp(true)}
                      disabled={!status.can_set_pin}>
                Set a PIN
              </button>
            )}
            {!status.can_set_pin && (
              <div style={{ fontSize: '12px', color: '#666', marginTop: '8px' }}>
                A PIN can only be set from Sophie&rsquo;s own network, not the one
                you are connected through now.
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="control-grid">
          <div className="control-item">
            <h3>Change PIN</h3>
            <div style={{ fontSize: '12px', color: '#666', marginBottom: '12px' }}>
              This device is trusted for another {trustedFor(status.expires_in)}.
              Changing the PIN also signs every other device out.
            </div>

            {stage === 'idle' ? (
              <button className="control-btn" onClick={() => setStage('current')}>
                Change PIN
              </button>
            ) : (
              <div>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>
                  {stage === 'current' ? 'Enter the current PIN'
                    : stage === 'new' ? 'Enter the new PIN'
                      : 'Re-enter the new PIN'}
                </div>
                <Keypad value={value} setValue={setValue} disabled={busy} />
                {error && <Message negative size="small">{error}</Message>}
                <div style={{ marginTop: '10px', display: 'flex', gap: '8px' }}>
                  <Button primary loading={busy} onClick={advance}
                          disabled={busy || value.length < 4}>
                    {stage === 'confirm' ? 'Change PIN' : 'Next'}
                  </Button>
                  <Button onClick={reset} disabled={busy}>Cancel</Button>
                </div>
              </div>
            )}
          </div>

          <div className="control-item">
            <h3>Forget all devices</h3>
            <div style={{ fontSize: '12px', color: '#666', marginBottom: '12px' }}>
              Use this if a phone or tablet is lost. Every device must enter the
              PIN again, including this one. The PIN itself does not change.
            </div>
            {confirmForget ? (
              <div className="control-buttons">
                <button className="control-btn danger" onClick={forgetAll} disabled={busy}>
                  Yes, sign all out
                </button>
                <button className="control-btn" onClick={() => setConfirmForget(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button className="control-btn" onClick={() => setConfirmForget(true)}
                      disabled={busy}>
                Forget all devices
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SecurityCard;
