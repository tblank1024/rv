import React, { useEffect } from 'react';
import { Outlet, Link, useNavigate } from "react-router-dom";
import { Button, Modal } from "semantic-ui-react";
import { useState } from 'react';
import { fetchFromServer, getServerUrl } from '../utils/api';
import { PinPrompt } from '../components/PinPrompt';
import './layout.css';


function TogglableButton(props) {
  let { text, activeColor, state, onClick } = props;
  const [active, setActive] = useState(false)
  const [busy, setBusy] = useState(false)
  async function handleClick(){
    console.log("Button clicked: " + text);
    const next = !active;
    setActive(next);              // optimistic
    setBusy(true);
    try {
      // Reverted when the server refuses -- a disarm now needs the PIN, and
      // showing "off" while the alarm is still armed would be the one lie
      // this button must never tell.
      const ok = await onClick(next);
      if (!ok) setActive(!next);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    setActive(state);
  }, [state])

  const bg = active
    ? (activeColor === 'blue' ? '#2185d0' : '#db2828')
    : '#555';

  return (
    <button
      onClick={handleClick}
      disabled={busy}
      className="nav-alarm-btn"
      style={{ backgroundColor: bg }}
    >
      {text}
    </button>
  )
}

/**
 * Returns {ok, pinRequired}. Arming is never refused; DISARMING needs the
 * dashboard PIN, because it is the only genuine security control in the RV
 * and anyone with Sophie's WiFi password could otherwise turn it off. The
 * server enforces that (see the alarm handler in server.py); this just has to
 * cope with being told no.
 */
async function tellServerAlarmStateChanged(state, alarmName){
  console.log("Alarm state changed: " + state + " " + alarmName)
  let url = `${getServerUrl()}/api/alarmpost`;
  try {
    const response = await fetch(url, {
      method: "POST",
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        "state": state,
        "alarm": alarmName,
      })
    });
    if (response.status === 401) return { ok: false, pinRequired: true };
    return { ok: response.ok, pinRequired: false };
  } catch (error) {
    console.error('Alarm request failed:', error);
    return { ok: false, pinRequired: false };
  }
}

function Layout() {
  let [bikeAlarmState, setBikeAlarmState] = useState(false);
  let [interiorAlarmState, setInteriorAlarmState] = useState(false);
  // The disarm the PIN prompt is standing in front of, so it can be retried
  // once unlocked rather than making the user tap the alarm again.
  const [pinFor, setPinFor] = useState(null);

  function getAlarmStatesFromServer(){
    fetchFromServer('/api/alarmget')
    .then(data => {
      setBikeAlarmState(data.bike);
      setInteriorAlarmState(data.interior);
    })
    .catch(error => {
      console.error('Error fetching alarm states:', error);
    });
  }

  useEffect(() => {
    getAlarmStatesFromServer();
    const interval = setInterval(() => {
      getAlarmStatesFromServer();
    }, 5000);
    return () => clearInterval(interval);
  }, [])

  // Sends the change and reports whether it stuck, so the button can revert.
  // A refusal parks the attempt in pinFor and raises the prompt.
  const sendAlarm = async (state, alarmName) => {
    const result = await tellServerAlarmStateChanged(state, alarmName);
    if (result.pinRequired) {
      setPinFor({ state, alarmName });
      return false;
    }
    if (result.ok) getAlarmStatesFromServer();
    return result.ok;
  };

  // Finish what the PIN was asked for, rather than making the user find the
  // alarm button again.
  const afterUnlock = async () => {
    const pending = pinFor;
    setPinFor(null);
    if (pending) {
      await tellServerAlarmStateChanged(pending.state, pending.alarmName);
    }
    getAlarmStatesFromServer();
  };

  return (
    <div className="layout-root">
      <nav className="app-nav">
        <Link className="nav-link" to="/">Home</Link>
        <Link className="nav-link" to="/power">Power</Link>
        <Link className="nav-link" to="/internet">Internet</Link>
        <Link className="nav-link" to="/wifi">Plex-Svr</Link>
        <TogglableButton onClick={(active) => sendAlarm(active, "bike")}
                         state={bikeAlarmState} text="Bike Alarm" activeColor="blue" />
        <TogglableButton onClick={(active) => sendAlarm(active, "interior")}
                         state={interiorAlarmState} text="Interior Alarm" activeColor="red" />
      </nav>
      <Outlet />

      <Modal open={!!pinFor} size="tiny"
             onClose={() => { setPinFor(null); getAlarmStatesFromServer(); }}>
        <Modal.Content>
          <PinPrompt
            reason={pinFor
              ? `Turning the ${pinFor.alarmName} alarm off needs the PIN.`
              : ''}
            onUnlocked={afterUnlock}
            onCancel={() => { setPinFor(null); getAlarmStatesFromServer(); }}
          />
        </Modal.Content>
      </Modal>
    </div>
  )
};

export default Layout;
