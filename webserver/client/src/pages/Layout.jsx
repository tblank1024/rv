import React, { useEffect } from 'react';
import { Outlet, Link, useNavigate } from "react-router-dom";
import { Button } from "semantic-ui-react";
import { useState } from 'react';
import { fetchFromServer, getServerUrl } from '../utils/api';
import './layout.css';


function TogglableButton(props) {
  let { text, activeColor, state, onClick } = props;
  const [active, setActive] = useState(false)
  function handleClick(){
    console.log("Button clicked: " + text);
    setActive((active) => !active);
    onClick(!active);
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
      className="nav-alarm-btn"
      style={{ backgroundColor: bg }}
    >
      {text}
    </button>
  )
}

function tellServerAlarmStateChanged(state, alarmName){
  console.log("Alarm state changed: " + state + " " + alarmName)
  let url = `${getServerUrl()}/api/alarmpost`;
  fetch(url, {
    method: "POST",
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    },
    body: JSON.stringify({
      "state": state,
      "alarm": alarmName,
    })
  })
}

function ToggleBikeAlarm(active) {
  console.log("Bike alarm is now " + active);
  tellServerAlarmStateChanged(active, "bike");
}

function ToggleInteriorAlarm(active) {
  console.log("Interior alarm is now " + active);
  tellServerAlarmStateChanged(active, "interior");
}

function Layout() {
  let [bikeAlarmState, setBikeAlarmState] = useState(false);
  let [interiorAlarmState, setInteriorAlarmState] = useState(false);

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

  return (
    <div className="layout-root">
      <nav className="app-nav">
        <Link className="nav-link" to="/">Home</Link>
        <Link className="nav-link" to="/power">Power</Link>
        <Link className="nav-link" to="/internet">Internet</Link>
        <Link className="nav-link" to="/wifi">Plex-Svr</Link>
        <TogglableButton onClick={ToggleBikeAlarm} state={bikeAlarmState} text="Bike Alarm" activeColor="blue" />
        <TogglableButton onClick={ToggleInteriorAlarm} state={interiorAlarmState} text="Interior Alarm" activeColor="red" />
      </nav>
      <Outlet />
    </div>
  )
};

export default Layout;
