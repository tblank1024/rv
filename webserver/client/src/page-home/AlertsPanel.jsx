import React, { useCallback, useEffect, useState } from "react";
import mqtt from 'mqtt';
import { Modal, Button } from 'semantic-ui-react';
import { fetchFromServer } from '../utils/api';

// The watcher (rv/watcher/watcher.py) publishes RVC/SYS_ERRORS on the broker:
// individual alert events, plus a heartbeat every ~5 s of the form
// {"error": "# Errors = N", "active": [...], "recent": [...]}. The heartbeat
// carries the full active list, so a page opened after an alert fired can
// still show it. Port 9001 is the broker's anonymous read-only websocket.
const SYS_ERRORS_TOPIC = 'RVC/SYS_ERRORS';
const HEARTBEAT_RE = /^#\s*Errors\s*=\s*(\d+)/;
const ACK_POLL_MS = 15000;

const GROUPS = [
  [/^(INVERTER|CHARGER)_/, 'Inverter/Charger'],
  [/^DM_RV/, 'RV-C diagnostics'],
  [/^BATTERY_/, 'Battery'],
  [/^ATS_/, 'Transfer switch'],
  [/^SOLAR_/, 'Solar'],
  [/^TANK_/, 'Tanks'],
  [/^TIRE_/, 'Tires'],
  [/^RV_Watcher/, 'Raspberry Pi'],
  [/^RV_Loads/, 'RV loads'],
];

function groupName(topic) {
  const hit = GROUPS.find(([re]) => re.test(topic || ''));
  return hit ? hit[1] : (topic || 'Other');
}

const alertKey = (a) => `${a.alias}|${a.kind}|${a.since}`;
const signalName = (alias) => alias.replace(/_/g, ' ');

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function formatAge(ts) {
  if (!ts) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function describe(a) {
  if (a.kind === 'bounds') {
    const [lo, hi] = a.bounds || [];
    return `value ${a.value} outside ${lo}–${hi} since ${formatTime(a.since)}`;
  }
  return `no data since ${formatTime(a.since)} (${formatAge(a.since)})`;
}

function summarize(items) {
  const silent = items.filter(a => a.kind === 'silent').length;
  const bounds = items.length - silent;
  const parts = [];
  if (silent) parts.push(`${silent} silent`);
  if (bounds) parts.push(`${bounds} out of range`);
  const earliest = Math.min(...items.map(a => a.since || Infinity));
  return `${parts.join(', ')}${Number.isFinite(earliest) ? ` since ${formatTime(earliest)}` : ''}`;
}

function AlertsPanel() {
  const [count, setCount] = useState(0);
  const [active, setActive] = useState(null); // null until a heartbeat with detail arrives
  const [recent, setRecent] = useState([]);
  const [ackKeys, setAckKeys] = useState(new Set());
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(new Set());
  const [ackError, setAckError] = useState('');

  useEffect(() => {
    const client = mqtt.connect(`ws://${window.location.hostname}:9001`);
    client.on('connect', () => client.subscribe(SYS_ERRORS_TOPIC));
    client.on('message', (topic, payload) => {
      let msg;
      try { msg = JSON.parse(payload.toString()); } catch { return; }
      if (typeof msg.error !== 'string') return;
      const m = msg.error.match(HEARTBEAT_RE);
      if (!m) return; // individual events show up in the next heartbeat's "recent"
      setCount(parseInt(m[1], 10));
      if (Array.isArray(msg.active)) setActive(msg.active);
      if (Array.isArray(msg.recent)) setRecent(msg.recent);
    });
    client.on('error', (err) => console.error('SYS_ERRORS MQTT error:', err));
    return () => client.end(true);
  }, []);

  const loadAcks = useCallback(() => {
    fetchFromServer('/api/alerts/ack')
      .then(r => setAckKeys(new Set(r.keys || [])))
      .catch(err => console.error('Alert ack fetch error:', err));
  }, []);

  useEffect(() => {
    loadAcks();
    const t = setInterval(loadAcks, ACK_POLL_MS);
    return () => clearInterval(t);
  }, [loadAcks]);

  const activeList = active || [];
  const unacked = activeList.filter(a => !ackKeys.has(alertKey(a)));
  // Older watcher builds send only the count; treat it as unacknowledged.
  const alarmCount = active ? unacked.length : count;

  const groups = {};
  activeList.forEach(a => { (groups[groupName(a.topic)] = groups[groupName(a.topic)] || []).push(a); });
  const groupEntries = Object.entries(groups);

  const acknowledge = () => {
    setAckError('');
    fetchFromServer('/api/alerts/ack', {
      method: 'POST',
      body: JSON.stringify({ keys: activeList.map(alertKey) }),
    })
      .then(r => {
        if (r.success) setAckKeys(new Set(r.keys));
        else setAckError(r.message || 'Acknowledge failed');
      })
      .catch(err => setAckError(`Acknowledge failed: ${err.message}`));
  };

  const toggle = (name) => setExpanded(prev => {
    const next = new Set(prev);
    next.has(name) ? next.delete(name) : next.add(name);
    return next;
  });

  const openDialog = () => { loadAcks(); setOpen(true); };

  let title = 'Alerts';
  if (alarmCount > 0) title = `Alerts (${alarmCount})`;
  else if (activeList.length > 0) title = `Alerts (${activeList.length} acknowledged)`;

  return (
    <>
      <div
        className={`sys-alerts sys-alerts--clickable${alarmCount > 0 ? ' sys-alerts--active' : ''}`}
        role="button"
        tabIndex={0}
        onClick={openDialog}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDialog(); } }}
      >
        <div className="sys-alerts-title">
          <span>{title}</span>
          <span className="sys-alerts-hint">Details ›</span>
        </div>
        {groupEntries.length === 0 ? (
          <div className="sys-alert-item sys-alert-item--none">
            {count > 0 && !active ? `${count} active (details unavailable)` : 'No active alerts'}
          </div>
        ) : (
          groupEntries.map(([name, items]) => {
            const acked = items.every(a => ackKeys.has(alertKey(a)));
            return (
              <div key={name} className={`sys-alert-item${acked ? ' sys-alert-item--acked' : ''}`}>
                {name}: {summarize(items)}
              </div>
            );
          })
        )}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} size="small" closeIcon>
        <Modal.Header>
          {activeList.length > 0 ? `Alerts: ${activeList.length} active` : 'Alerts'}
          {activeList.length > 0 && unacked.length === 0 && (
            <span className="alerts-dialog-acked"> (all acknowledged)</span>
          )}
        </Modal.Header>
        <Modal.Content scrolling>
          {groupEntries.length === 0 ? (
            <p className="alerts-dialog-none">No active alerts.</p>
          ) : (
            groupEntries.map(([name, items]) => {
              const isOpen = expanded.has(name);
              const acked = items.every(a => ackKeys.has(alertKey(a)));
              return (
                <div key={name} className={`alerts-group${acked ? ' alerts-group--acked' : ''}`}>
                  <button type="button" className="alerts-group-head" onClick={() => toggle(name)} aria-expanded={isOpen}>
                    <span className="alerts-group-caret">{isOpen ? '▾' : '▸'}</span>
                    <span className="alerts-group-name">{name}</span>
                    <span className="alerts-group-summary">{summarize(items)}</span>
                  </button>
                  {isOpen && (
                    <ul className="alerts-group-items">
                      {items.map(a => (
                        <li key={alertKey(a)} className={ackKeys.has(alertKey(a)) ? 'alerts-item--acked' : ''}>
                          <strong>{signalName(a.alias)}</strong>: {describe(a)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })
          )}

          <h4 className="alerts-history-title">Recent history</h4>
          {recent.length === 0 ? (
            <p className="alerts-dialog-none">No alerts since the watcher last started.</p>
          ) : (
            <ul className="alerts-history">
              {[...recent].reverse().map((r, i) => (
                <li key={`${r.timestamp}-${i}`}>
                  <span className="alerts-history-time">{formatTime(r.timestamp)}</span> {r.error}
                </li>
              ))}
            </ul>
          )}
          {ackError && <p className="alerts-dialog-error">{ackError}</p>}
        </Modal.Content>
        <Modal.Actions>
          <Button onClick={acknowledge} disabled={unacked.length === 0} color="orange">
            Acknowledge
          </Button>
          <Button onClick={() => setOpen(false)}>Close</Button>
        </Modal.Actions>
      </Modal>
    </>
  );
}

export default AlertsPanel;
