import React, { useEffect, useRef, useState } from "react";
import BatteryGauge from "react-battery-gauge";
import { fetchFromServer } from '../utils/api';
import Gauge from '../components/gauge1';
import './Home.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract the numeric value from strings like "54 psi", "-72°F", "--". */
function parseTireNum(str) {
  if (!str) return null;
  const m = String(str).match(/-?\d+(\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

/** Render a single tire box with alert-coloring for negative values. */
function TireCell({ label, psiStr, tempStr, className }) {
  const psi  = parseTireNum(psiStr);
  const temp = parseTireNum(tempStr);
  const alert = (psi !== null && psi < 0) || (temp !== null && temp < 0);
  const stale = psi === null; // server returns "-- psi" once the MQTT reading exceeds its TTL
  const dispPsi  = psi  !== null ? `${Math.abs(psi)} psi` : (psiStr  || '--');
  const dispTemp = temp !== null ? `${Math.abs(temp)}°F`  : (tempStr || '');

  const classes = ['tire'];
  if (className) classes.push(className);
  if (alert)     classes.push('tire--alert');
  if (stale)     classes.push('tire--stale');

  return (
    <div className={classes.join(' ')}>
      <div className="tire-label">{label}</div>
      <div className="tire-reading">{dispPsi}</div>
      <div className="tire-reading">{dispTemp}</div>
    </div>
  );
}

/** Return a Set of tire-position keys that currently have a fault (negative value). */
function getFaultSet(d) {
  const checks = [
    { key: 'LF',     psi: d.var9,  temp: d.tire_lf_temp },
    { key: 'RF',     psi: d.var10, temp: d.tire_rf_temp },
    { key: 'RL_out', psi: d.var1,  temp: d.tire_lr_out_temp },
    { key: 'RL_in',  psi: d.var2,  temp: d.tire_lr_in_temp  },
    { key: 'RR_in',  psi: d.var3,  temp: d.tire_rr_in_temp  },
    { key: 'RR_out', psi: d.var4,  temp: d.tire_rr_out_temp },
  ];
  const faults = new Set();
  checks.forEach(({ key, psi, temp }) => {
    const p = parseTireNum(psi);
    const t = parseTireNum(temp);
    if ((p !== null && p < 0) || (t !== null && t < 0)) faults.add(key);
  });
  return faults;
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

function Home() {
  const [data, setData] = useState({});
  const [tireRunning, setTireRunning] = useState(null); // null = unknown
  const [restarting, setRestarting] = useState(false);
  const [rebooting, setRebooting] = useState(false);
  const [confirmReboot, setConfirmReboot] = useState(false);
  const [tireFaultSilenced, setTireFaultSilenced] = useState(false);
  const serverWentDown = useRef(false);
  const tireStatusLockedUntil = useRef(0); // epoch ms — ignore poll results until this time
  const tireFaultSilencedRef = useRef(false); // mirror for use inside setInterval closure
  const silencedFaultSet = useRef(new Set()); // tire keys faulted when silence was pressed

  const getData = () => {
    fetchFromServer('/data/home')
      .then(myJson => {
        setData(myJson);
        if (serverWentDown.current) {
          serverWentDown.current = false;
          setRestarting(false);
          setRebooting(false);
        }
        // Reset silenced state if faults cleared or a new (previously un-silenced) fault appears
        if (tireFaultSilencedRef.current) {
          const currentFaults = getFaultSet(myJson);
          if (currentFaults.size === 0) {
            tireFaultSilencedRef.current = false;
            setTireFaultSilenced(false);
          } else {
            let hasNewFault = false;
            currentFaults.forEach(tire => {
              if (!silencedFaultSet.current.has(tire)) hasNewFault = true;
            });
            if (hasNewFault) {
              tireFaultSilencedRef.current = false;
              setTireFaultSilenced(false);
            }
          }
        }
      })
      .catch(error => {
        console.error('Error fetching data:', error);
        serverWentDown.current = true;
        setData({ var17: '0', var18: '0', var13: '0', var14: '0', battery_percent: 0 });
      });
  };

  const fetchTireServiceStatus = () => {
    fetchFromServer('/api/tire/service')
      .then(r => {
        if (Date.now() >= tireStatusLockedUntil.current) {
          setTireRunning(r.running);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    const dataInterval = setInterval(getData, 1000);
    fetchTireServiceStatus();
    const svcInterval  = setInterval(fetchTireServiceStatus, 10000);
    return () => { clearInterval(dataInterval); clearInterval(svcInterval); };
  }, []);

  const handleReboot = () => setConfirmReboot(true);

  const doReboot = () => {
    setConfirmReboot(false);
    serverWentDown.current = false;
    setRebooting(true);
    fetchFromServer('/api/system/reboot', { method: 'POST' })
      .catch(err => { console.error('Reboot error:', err); setRebooting(false); });
  };

  const handleRestart = () => {
    serverWentDown.current = false;
    setRestarting(true);
    fetchFromServer('/api/system/restart-containers', { method: 'POST' })
      .catch(err => { console.error('Restart error:', err); setRestarting(false); });
  };

  const handleTireService = () => {
    const action = tireRunning ? 'stop' : 'start';
    const optimistic = action === 'start';
    tireStatusLockedUntil.current = Date.now() + 12000; // block polls for 12 s
    setTireRunning(optimistic); // update immediately for instant visual feedback
    fetchFromServer('/api/tire/service', {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
      .then(r => { if (!r.success) { tireStatusLockedUntil.current = 0; setTireRunning(!optimistic); } })
      .catch(err => { console.error('Tire service error:', err); tireStatusLockedUntil.current = 0; setTireRunning(!optimistic); });
  };

  const handleSilenceAlarm = () => {
    const faults = getFaultSet(data);
    silencedFaultSet.current = faults;
    tireFaultSilencedRef.current = true;
    setTireFaultSilenced(true);
    fetchFromServer('/api/tire/silence', { method: 'POST' })
      .catch(err => console.error('Silence error:', err));
  };

  return (
    <div className="Home">
      {confirmReboot && (
        <div className="confirm-overlay">
          <div className="confirm-dialog">
            <p className="confirm-msg">Confirm reboot?</p>
            <div className="confirm-buttons">
              <button className="confirm-btn confirm-btn--yes" onClick={doReboot}>Yes</button>
              <button className="confirm-btn confirm-btn--no" onClick={() => setConfirmReboot(false)}>No</button>
            </div>
          </div>
        </div>
      )}
      <div className="home-wrapper">

        {/* ── Header bar ─────────────────────────── */}
        <div className="home-header">
          <span className="home-title">RV Status</span>
          <span className="home-time">{data.var20}</span>
        </div>

        {/* ── Main grid ──────────────────────────── */}
        <div className="home-grid">

          {/* ── Tires card ─────────────────────── */}
          <div className="home-card home-card--tires">
            <div className="card-title">
              {getFaultSet(data).size > 0 ? 'Tire Info (Faults)' : 'Tire Info (No Faults)'}
            </div>
            <div className="tire-diagram">
              <div className="tire-axle-label">Front</div>
              <div className="tire-axle">
                <TireCell label="Left"  psiStr={data.var9}  tempStr={data.tire_lf_temp} />
                <div className="tire-chassis"/>
                <TireCell label="Right" psiStr={data.var10} tempStr={data.tire_rf_temp} />
              </div>
              <div className="tire-axle-label">Rear</div>
              <div className="tire-axle">
                <TireCell label="Left-Out" psiStr={data.var1} tempStr={data.tire_lr_out_temp} />
                <TireCell label="Left-In"  psiStr={data.var2} tempStr={data.tire_lr_in_temp}  className="tire--inner" />
                <div className="tire-chassis"/>
                <TireCell label="Right-In"  psiStr={data.var3} tempStr={data.tire_rr_in_temp}  className="tire--inner" />
                <TireCell label="Right-Out" psiStr={data.var4} tempStr={data.tire_rr_out_temp} />
              </div>
            </div>
            <div className="tire-controls">
              <button
                className={`tire-btn${tireRunning ? ' tire-btn--start' : ' tire-btn--stop'}`}
                onClick={handleTireService}
              >
                {tireRunning === null ? 'Service ...' : tireRunning ? 'Running - Press to Stop' : 'Stopped - Press to Start'}
              </button>
              {(() => {
                const tireAlarmActive = getFaultSet(data).size > 0;
                let cls = 'tire-btn';
                let label = 'Silence Alarm';
                if (!tireAlarmActive) {
                  cls += ' tire-btn--silence-idle';
                } else if (tireFaultSilenced) {
                  cls += ' tire-btn--silence-silenced';
                  label = 'Fault Silenced';
                } else {
                  cls += ' tire-btn--silence-active';
                }
                return (
                  <button className={cls} onClick={handleSilenceAlarm}>
                    {label}
                  </button>
                );
              })()}
            </div>
          </div>

          {/* ── Tanks card ─────────────────────── */}
          <div className="home-card home-card--tanks">
            <div className="card-title">Tanks</div>
            <div className="tanks-grid">
              <Gauge value={data.var17} label="Fresh"   id="fresh"   startColor="#24E9EF" endColor="#24E9EF" radius={35}/>
              <Gauge value={data.var18} label="Propane" id="propane" startColor="#FF8C00" endColor="#FF8C00" radius={35}/>
              <Gauge value={data.var13} label="Gray"    id="gray"    startColor="#888888" endColor="#888888" radius={35}/>
              <Gauge value={data.var14} label="Black"   id="black"   startColor="#333333" endColor="#333333" radius={35}/>
            </div>
          </div>

          {/* ── Power card ─────────────────────── */}
          <div className="home-card home-card--power">
            <div className="card-title">
              {data.shore_power_active ? 'Power from Shore' : 'Power from Battery'}
            </div>
            <div className="power-row">
              <div className="power-item power-item--solar">
                <div className="power-item-header">
                  <span className="power-icon">☀️</span>
                  <span className="power-label">Solar</span>
                </div>
                <div className="power-value">{data.var5}</div>
              </div>
              <div className="power-item power-item--ac">
                <div className="power-item-header">
                  <span className="power-icon">🔌</span>
                  <span className="power-label">AC Coach</span>
                </div>
                <div className="power-value">{data.var12}</div>
              </div>
              <div className="power-item power-item--dc">
                <div className="power-item-header">
                  <span className="power-icon">⚡</span>
                  <span className="power-label">DC Load</span>
                </div>
                <div className="power-value">{data.var8}</div>
              </div>
            </div>
          </div>

          {/* ── Battery card ───────────────────── */}
          <div className="home-card home-card--battery">
            <div className="card-title">Battery</div>
            <div className="battery-body">
              <div className="battery-stats">
                <div className="stat-row">
                  <span className="stat-label">Voltage</span>
                  <span className="stat-value">{data.var7}</span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Power</span>
                  <span className="stat-value">{data.var19}</span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Remaining</span>
                  <span className="stat-value">{data.var15}</span>
                </div>
                <div className="stat-row">
                  <span className="stat-label">Status</span>
                  <span className="stat-value">{data.var16}</span>
                </div>
              </div>
              <div className="battery-widget">
                <BatteryGauge
                  value={data.battery_percent || 0}
                  size={110}
                  padding={4}
                  aspectRatio={0.5}
                />
              </div>
            </div>
          </div>

          {/* ── Action buttons ─────────────────── */}
          <div className="home-card home-card--actions">
            <div className="card-title">System</div>
            <div className="action-buttons">
              <button className="action-btn action-btn--restart" onClick={handleRestart} disabled={restarting}>
                {restarting ? 'Restarting' : 'Restart Program'}
              </button>
              <button className="action-btn action-btn--debug" onClick={() => { window.location.href = '/debug'; }}>
                Debug
              </button>
              <button className="action-btn action-btn--reboot" onClick={handleReboot} disabled={rebooting}>
                {rebooting ? 'Rebooting' : 'Reboot'}
              </button>
            </div>
          </div>

        </div> {/* end home-grid */}
      </div>   {/* end home-wrapper */}
    </div>
  );
}

export default Home;

