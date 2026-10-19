/**
 * RV Internet Connection Management Page
 *
 * === THE MODEL (rewritten 2026-10-19) ===
 * WAN sources live on the Plugable powered hub, one physical socket each, and
 * are selected BY ROLE rather than by port number: the user picks "starlink",
 * not "socket 4". Roles come from /etc/usbhub/sockets.json via
 * /api/hub/wan. Exactly one roled socket is powered at a time, which is the
 * power-saving goal -- several uplinks may be *considered*, only one is left
 * drawing current.
 *
 * Sockets WITHOUT a role are never touched by a switch here. That is what
 * stops a WAN change from cutting the Bluetooth adapter in socket 7, and it is
 * also why socket 1 (the WiFi adapter) has a display *name* but no role: see
 * the names/wan split in usbhub_ports.py.
 *
 * === WHAT THIS PAGE DOES NOT DO ===
 * Powering a socket OFFERS an uplink; it does not seize the default route.
 * pi5connect.sh decides that on the interface event which follows, and from
 * v2.2 it also promotes a replacement when the current WAN goes down. So the
 * "Connection Status" card reports the route the system actually chose, which
 * can legitimately differ from the socket selected above.
 *
 * === WHAT WAS REMOVED ===
 * The Coolgear USB switch selector. That hub was physically removed on
 * 2026-10-19; /dev/coolgear-hub no longer exists and the endpoints behind it
 * return "USB hub controller not available". Its radio group, its per-type
 * initialisation delays, its countdown and its connect/abort state machine are
 * all gone. Git history has them if the hub ever returns.
 *
 * === KASA ACCESSORIES ===
 * Still real hardware, and they lost their only UI when the Coolgear card went:
 * outlet 1 is the cellular signal amplifier, outlet 6 the Starlink power
 * supply. Both are plain switched outlets, unrelated to which USB socket is
 * powered, so they get their own card with live wattage.
 *
 * === WIFI ===
 * Rendered by WifiPicker.jsx, always. The uplink radio is selected by the
 * picker, not by this page's WAN card -- and it must not be gated on a WAN
 * selection, because gating it behind a radio button meant reaching the picker
 * required dropping the live WAN.
 * NOTE: the route /wifi belongs to the Plex page, not to any of this.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Form, Message, Card, Header, Icon, Radio, Button, Label } from 'semantic-ui-react';
import './Internet.css';
import { fetchFromServer } from '../utils/api';
import WifiPicker from './WifiPicker';

// Kasa outlets that are internet accessories. Numbers are the strip's own.
const KASA_AMP = 1;
const KASA_STARLINK = 6;

const Internet = () => {
  // Powered-hub WAN selection
  const [wanCandidates, setWanCandidates] = useState([]);
  const [wanActive, setWanActive] = useState(null);
  const [wanPoweredPresent, setWanPoweredPresent] = useState([]);
  const [wanConfigured, setWanConfigured] = useState(null);
  const [wanBusy, setWanBusy] = useState(false);
  const [wanMessage, setWanMessage] = useState('');

  // The route the system actually took
  const [wanInterface, setWanInterface] = useState(null);  // null until read
  const [routeStatus, setRouteStatus] = useState(null);

  // Connectivity test
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);   // {connected, message}

  // Kasa accessories
  const [ampPower, setAmpPower] = useState(null);
  const [starlinkPower, setStarlinkPower] = useState(null);
  const [kasaBusy, setKasaBusy] = useState(false);

  // ---- powered hub ------------------------------------------------------
  const fetchHubWan = useCallback(async () => {
    try {
      const response = await fetchFromServer('/api/hub/wan');
      if (response && response.success) {
        setWanCandidates(response.candidates || []);
        setWanActive(response.active || null);
        setWanPoweredPresent(response.powered_present || []);
        setWanConfigured(!!response.configured);
        setWanMessage(response.message || '');
      } else {
        setWanConfigured(false);
        setWanMessage((response && response.message) || 'Hub API unavailable');
      }
    } catch (error) {
      setWanConfigured(false);
      setWanMessage('Could not reach the hub API: ' + error.message);
    }
  }, []);

  const selectHubWan = async (role) => {
    setWanBusy(true);
    // No optimistic update: a switch is a USB control transfer per identity and
    // takes seconds, so the radio must not move before the kernel confirms it.
    try {
      const response = await fetchFromServer('/api/hub/wan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
      setWanMessage((response && response.message) || '');
    } catch (error) {
      setWanMessage('Switch failed: ' + error.message);
    } finally {
      await fetchHubWan();
      await fetchRoute();
      setWanBusy(false);
    }
  };

  // ---- the real default route -------------------------------------------
  const fetchRoute = useCallback(async () => {
    try {
      const response = await fetchFromServer('/api/internet/status');
      setWanInterface(response.wan_interface || '');
      setRouteStatus(response.status || null);
    } catch (error) {
      console.error('Failed to read internet status:', error);
      setWanInterface('');
      setRouteStatus(null);
    }
  }, []);

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await fetchFromServer('/api/internet/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connection_type: wanActive || 'wired' }),
      });
      setTestResult({
        connected: !!(response && response.connected),
        message: (response && response.message) || '',
      });
    } catch (error) {
      setTestResult({ connected: false, message: error.message });
    } finally {
      await fetchRoute();
      setTesting(false);
    }
  };

  // ---- Kasa accessories --------------------------------------------------
  const fetchKasaPower = useCallback(async () => {
    try {
      const amp = await fetchFromServer(`/api/kasa/power/${KASA_AMP}`);
      if (amp.success) setAmpPower(amp.power);
      const star = await fetchFromServer(`/api/kasa/power/${KASA_STARLINK}`);
      if (star.success) setStarlinkPower(star.power);
    } catch (error) {
      console.error('Failed to fetch Kasa power readings:', error);
    }
  }, []);

  const setKasaOutlet = async (outlet, action) => {
    setKasaBusy(true);
    try {
      await fetchFromServer(`/api/debug/kasa/${outlet}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
    } catch (error) {
      console.error('Kasa control failed:', error);
    } finally {
      await fetchKasaPower();
      setKasaBusy(false);
    }
  };

  useEffect(() => {
    fetchHubWan();
    fetchRoute();
    fetchKasaPower();
  }, [fetchHubWan, fetchRoute, fetchKasaPower]);

  // A candidate's display name: the socket's cosmetic label if the map has
  // one, else the role itself.
  const candidateName = (cand) => cand.name || cand.role;

  return (
    <div className="internet-page">
      <div className="internet-container">
        <Header as="h1" icon textAlign="center">
          <Icon name="wifi" />
          <Header.Content>
            Internet Connection
            <Header.Subheader>Choose which uplink is powered</Header.Subheader>
          </Header.Content>
        </Header>

        {/* ---- WAN source, by role ---------------------------------------- */}
        <Card className="internet-control-card" fluid>
          <Card.Content>
            <Card.Header>WAN Source</Card.Header>
            <Card.Meta>
              One socket powered at a time. Sockets with no WAN role are left
              alone, so switching here cannot cut Bluetooth or the WiFi adapter.
            </Card.Meta>
            {wanConfigured === false ? (
              <Message warning size="small" style={{ marginTop: '10px' }}>
                {wanMessage || 'No socket map yet. Build one with rv/usbhub/map_sockets.py.'}
              </Message>
            ) : (
              <Form style={{ marginTop: '12px' }}>
                {wanCandidates.map(cand => (
                  <Form.Field key={cand.role}>
                    <Radio
                      label={
                        `${candidateName(cand)} — socket ${cand.socket}` +
                        (cand.present
                          ? ` (${cand.product || 'device'}${cand.max_power ? ', ' + cand.max_power : ''})`
                          : ' — empty socket')
                      }
                      name="hubWanRole"
                      value={cand.role}
                      checked={wanActive === cand.role}
                      onChange={() => selectHubWan(cand.role)}
                      /* An empty socket is not selectable: powering one
                         enumerates nothing, which is exactly how "Wired"
                         appeared broken for weeks on the old hub. */
                      disabled={wanBusy || !cand.present}
                    />
                  </Form.Field>
                ))}
                <Form.Field>
                  <Radio
                    label="None (all WAN sockets off)"
                    name="hubWanRole"
                    value="none"
                    checked={wanActive === null && wanPoweredPresent.length === 0}
                    onChange={() => selectHubWan(null)}
                    disabled={wanBusy}
                  />
                </Form.Field>
              </Form>
            )}

            {wanBusy && (
              <div style={{ marginTop: '8px' }}>
                <Icon name="circle notched" loading /> Switching sockets…
              </div>
            )}

            {/* More than one powered means exclusivity has never been applied
                -- the state the hub is in after a fresh socket map. Saying so
                is better than showing an arbitrary radio as selected. */}
            {!wanBusy && wanPoweredPresent.length > 1 && (
              <Message warning size="small" style={{ marginTop: '10px' }}>
                {wanPoweredPresent.length} uplinks are powered at once
                ({wanPoweredPresent.join(', ')}). Pick one above to apply
                exclusivity.
              </Message>
            )}

            <Message info size="small" style={{ marginTop: '10px' }}>
              Powering a socket offers an uplink; it does not seize the default
              route. pi5connect.sh decides that on the interface event which
              follows, keeps a healthy incumbent rather than being preempted,
              and promotes a replacement if the current WAN drops.
            </Message>
          </Card.Content>
        </Card>

        {/* ---- the route the system actually chose ------------------------- */}
        <Card className="internet-control-card" fluid style={{ marginTop: '20px' }}>
          <Card.Content>
            <Card.Header>Connection Status</Card.Header>
            <Card.Meta>
              Read from the live routing table, not from which socket is
              powered. The two can differ, and that is not a fault.
            </Card.Meta>
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center',
                          justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
              <span>
                <strong>Default route: </strong>
                {wanInterface === null ? (
                  <><Icon name="circle notched" loading /> reading…</>
                ) : wanInterface ? (
                  <><Icon name="check circle" color="green" />
                    <Label basic>{wanInterface}</Label></>
                ) : (
                  <><Icon name="times circle" color="red" /> none</>
                )}
              </span>
              <Button size="small" onClick={runTest} loading={testing} disabled={testing}>
                <Icon name="exchange" /> Test connectivity
              </Button>
            </div>

            {routeStatus && wanInterface === '' && (
              <Message negative size="small" style={{ marginTop: '10px' }}>
                No default route. The RV has no internet; the LAN and SSH over
                br0 are unaffected.
              </Message>
            )}

            {testResult && (
              <Message
                size="small"
                positive={testResult.connected}
                negative={!testResult.connected}
                style={{ marginTop: '10px' }}
              >
                {testResult.message || (testResult.connected ? 'Reachable' : 'Not reachable')}
              </Message>
            )}
          </Card.Content>
        </Card>

        {/* ---- Kasa accessories ------------------------------------------- */}
        <Card className="internet-control-card" fluid style={{ marginTop: '20px' }}>
          <Card.Content>
            <Card.Header>Powered Accessories</Card.Header>
            <Card.Meta>
              Switched mains outlets, independent of which USB socket is
              powered. Starlink needs its outlet on as well as its socket.
            </Card.Meta>
            <div style={{ marginTop: '12px' }}>
              {[
                { outlet: KASA_AMP, name: 'Cellular signal amplifier', watts: ampPower },
                { outlet: KASA_STARLINK, name: 'Starlink power supply', watts: starlinkPower },
              ].map(item => (
                <div key={item.outlet}
                     style={{ display: 'flex', alignItems: 'center',
                              justifyContent: 'space-between', padding: '6px 0',
                              flexWrap: 'wrap', gap: '8px' }}>
                  <span>
                    {item.name}
                    {item.watts !== null && (
                      <Label basic size="small" style={{ marginLeft: '8px' }}>
                        {item.watts} W
                      </Label>
                    )}
                  </span>
                  <Button.Group size="mini">
                    <Button disabled={kasaBusy}
                            onClick={() => setKasaOutlet(item.outlet, 'on')}>On</Button>
                    <Button disabled={kasaBusy}
                            onClick={() => setKasaOutlet(item.outlet, 'off')}>Off</Button>
                  </Button.Group>
                </div>
              ))}
            </div>
          </Card.Content>
        </Card>

        {/* ---- WiFi -------------------------------------------------------- */}
        <div style={{ marginTop: '20px', marginBottom: '20px' }}>
          <WifiPicker />
        </div>
      </div>
    </div>
  );
};

export default Internet;
