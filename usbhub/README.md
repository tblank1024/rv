# usbhub — USB port power control

Two generations of hardware live here, and they are controlled in completely
different ways.

| File | Hub | Mechanism | Status |
|---|---|---|---|
| `usbhub_ports.py` | any hub, incl. the **Plugable** 7-in-1 | kernel per-port power (sysfs / `uhubctl`) | new, 2026-10-18 |
| `usbhub_api.py` + `usbhub-api.service` | same | root HTTP/JSON on `127.0.0.1:12347` | new, 2026-10-18 |
| `setup_usbhub_api.sh` | — | installs both into `/usr/local/sbin` | new |
| `../webserver/usbhub_ascii.py` | **Coolgear** 4-port switch | FT232R serial ASCII, `/dev/coolgear-hub` | **live** — what runs today |
| `usbhub_ctl.py`, `usbhub_ctl_pi.py` | Coolgear | serial, v16.0 @115200 and v20.0 @9600 | **stale duplicates** of the above at v20.1 |

Three copies of `CoolGearUSBHub` now exist. Only `webserver/usbhub_ascii.py`
is wired into the server. The two here are older protocol experiments kept from
the baud-rate investigation; diff before trusting either.

## Why the new hub needs a root service

The Coolgear is steered from inside the webserver container because its control
path is a **character device** (`/dev/coolgear-hub`), bind-mounted from the
host. A plain powered hub has no control chip, so port power goes through the
kernel — and that is closed to the container:

```
$ docker exec webserver grep ' /sys' /proc/mounts
sysfs /sys          rw
sysfs /sys/devices  ro        <- port attributes live under here
```

`/sys/bus/usb/devices/*` are symlinks into that read-only tree, so writing
`<hub>:1.0/<hub>-portN/disable` fails with `EACCES` even though the container is
privileged and uid 0 (verified 2026-10-18). Hence `usbhub-api.service`, which
is the same pattern as `wifi-api-rp5.service`: root, loopback, stdlib only,
with the bind address as the only access control. The alternative — making
`/sys/devices` writable in the container — runs against the direction the
compose file already sets ("privileged … document/trim in Phase 4 hardening").

## What "off" actually means

A disabled port is guaranteed to have **the device gone from the bus**. VBUS is
removed only if the hub really implements per-port power switching (the USB
LPSM field); hubs that gang their power, or that misreport, will drop the data
link while still feeding 5 V. `uhubctl` reports the claimed capability and the
API passes it through as `power_switching`, with `null` meaning *unknown* —
which is not the same as "no".

**If the point is saving power, confirm with a current measurement at the port.**
A device disappearing from `lsusb` is not evidence that it stopped drawing.

## Exclusivity is now policy, not protocol

The Coolgear's ASCII commands are a bitmask that turns exactly one port on, so
only one WAN could ever be powered. A plain hub has no such constraint, which is
why the two endpoints differ:

- `POST /api/hub/<hub>/port` — one port, others untouched, several may be on.
  For the **debug page**, where powering two at once is a diagnostic.
- `POST /api/hub/<hub>/exclusive` — power exactly one, switching the others off
  **first** so the hub never briefly feeds two WAN devices. For the **Internet
  page**, and the RV's normal policy: several WAN options may be *considered*,
  but only one is left drawing current.

`USBHUB_PROTECTED` ("hub:port", comma separated) refuses to switch a port off at
all. It defaults to `1-2:4`, the Coolgear's own FT232R — cutting that is a loss
of *control*, not of internet, and the hub cannot then be steered back — plus
`1-2:3`, the adapter carrying the live WAN, which is listed only while the
Coolgear is still the WAN switch (that path is steered over serial, not through
this service, so protecting it here costs nothing).

**Ports carrying another hub are protected automatically**, so cascades never
have to be listed by hand. On this machine that finds five:

```
usb1:2   the Coolgear's upstream   <- cutting it kills the live WAN
usb3:1   the Plugable's upstream, USB 2 side
usb4:1   the Plugable's upstream, USB 3 side
3-1:3    the Plugable's internal cascade, USB 2 side
4-1:3    the Plugable's internal cascade, USB 3 side
```

## One socket, two sysfs ports

A USB 3 hub is **two hubs in one shell**. A socket's SuperSpeed lanes go to a
USB 3 hub chip and its D+/D− pair to a separate USB 2 hub chip, on a different
bus. Measured on the Plugable, 2026-10-18 — one upstream cable:

```
3-1  +  3-1.3     USB 2 chips (bus 3)
4-1  +  4-1.3     USB 3 chips (bus 4)
```

A "7-in-1" is two 4-port chips **in series** on each speed, port 3 of the
upstream chip being the internal cascade — which is why 4 + 4 presents as 7.

So one physical socket has up to two sysfs identities, and a plugged device
appears under exactly one of them, whichever matches its own speed. A USB 2
stick in socket 3 is invisible on the USB 3 tree. Two consequences:

- A socket's state is the **union** of its identities.
- Switching a socket means acting on **every** identity. Which one gates VBUS
  is a board-layout question sysfs cannot answer, so both are set; setting one
  that is not wired to the switch is harmless.

### Exclusivity applies to WAN sockets only

`set_exclusive` switches only sockets that have a **WAN role** in the map, plus
the target. A socket with no role is not an uplink and is not touched.

That distinction is not cosmetic. The hub also carries things that are not
uplinks: with the ASUS BT500 in socket 7, an exclusive switch over *every*
socket would cut Bluetooth every time the WAN changed, taking the TPMS and
battery monitors with it. `all_off` is literal by choice, since "all off" has to
mean what it says, so the API's `/api/sockets/all-off` defaults to WAN sockets
and needs `{"all": true}` to cut the rest.

`SocketMap` handles this, and the socket endpoints (`/api/sockets`,
`/api/socket`, `/api/socket/exclusive`, `/api/sockets/all-off`) are what callers
should use. The raw `/api/hub/<hub>/port` endpoints act on half a socket.

Nothing relates a socket on the shell to a port number, so **the map is observed,
not derived**:

```bash
sudo /usr/local/sbin/map_sockets.py --hubs 3-1,3-1.3,4-1,4-1.3
```

Plug one device into a socket, label it, move it to the next. Run it twice —
once with a USB 2 device, once with a USB 3 one, giving each socket the same
label both times — so each socket ends up with both identities. It merges into
`/etc/usbhub/sockets.json`; `--out` writes elsewhere, `--fresh` starts over. An
absent map is a normal state: the socket endpoints answer 409 rather than guess,
because guessing here means cutting power to the wrong uplink.

## Probing a new hub

Everything the repo cannot know — which hub is which, how many ports, what is
attached, whether power switching works — comes from one command:

```bash
sudo /usr/local/sbin/usbhub_ports.py      # human-readable
sudo uhubctl                              # per-port power switching support
curl -s http://127.0.0.1:12347/api/hubs   # same data as JSON
```

Measured 2026-10-18 **after** the Plugable went in (one blue port, the Alfa
moved to the other):

```
usb1  port 1  (empty)                               <- Edimax BT was here
usb1  port 2  USB2.1 Hub (Coolgear)      100mA
1-2   port 3  USB 10/100 LAN             100mA      <- the live WAN
1-2   port 4  FT232R USB UART             90mA      <- Coolgear control chip
usb2  port 1  Wireless (Alfa MT7612U)    400mA      <- moved here, still wlan1
usb3  port 1  USB2.0 Hub (Plugable)        0mA      <- 3-1, then 3-1.3
usb3  port 2  ASUS USB-BT500             500mA
usb4  port 1  USB3.0 Hub (Plugable)        0mA      <- 4-1, then 4-1.3
```

All four Plugable chips report `ppps` (per-port power switching) to `uhubctl`,
which is the capability claim — not proof VBUS drops. See the warning above.

The Pi 5's two blue ports each carry both speeds on one connector: blue A is
`usb2:1` (SS) + `usb1:1` (HS), blue B is `usb4:1` + `usb3:1`. That is why the
Alfa's move from blue B to blue A **displaced the Edimax Bluetooth adapter**,
which shared blue A's USB 2 half. The `.link` MAC pinning held across the move —
the Alfa came back as `wlan1` on a different bus — but `hci1` is gone, and
`bat2mqtt` pins that adapter by MAC (`08:BE:AC:35:8E:5E`), so battery monitoring
stopped silently at 14:01:56. Plug the Edimax into the Plugable.

~1690 mA of *declared* draw against the 600 mA budget the Pi is running
(`usb_max_current_enable=0`, raise to 1.6 A with a 27 W PSU). `bMaxPower` is a
declared ceiling, not consumption, and `throttled=0x0` shows no undervoltage so
far — but note the two Bluetooth adapters claim more between them than the Alfa.

## The map, measured 2026-10-18

```
socket 1    3-1.3:3, 4-1.3:3        socket 5    3-1:2, 4-1:2
socket 2    3-1.3:2, 4-1.3:2        socket 6    3-1:1, 4-1:1
socket 3    3-1.3:1, 4-1.3:1        socket 7    3-1:4, 4-1:4
socket 4    3-1.3:4, 4-1.3:4
```

Two things worth having measured rather than assumed:

- **Physical order does not follow port order.** Sockets 1-4 are on the
  downstream chip in port order 3, 2, 1, 4; sockets 5-7 on the upstream chip in
  order 2, 1, 4. Nothing about the geometry was guessable.
- **Port numbering is identical across the two trees** — `3-1.3:3` and
  `4-1.3:3` are the same socket for every one of the seven. So the two chips'
  ports are wired to the connectors in the same order, which is what makes a
  second mapping pass a confirmation rather than a separate discovery.

### Which identity gates a device

With the AX88179B (SuperSpeed) in socket 7:

| action | result |
|---|---|
| disable the USB 2 identity only (`3-1:4`) | device **stays** |
| disable the USB 3 identity only (`4-1:4`) | device **gone** |

So a device is gated by the identity matching its own speed, and the two chips'
port power is **independent — not ganged to the connector's VBUS**. Disabling
the USB 2 half of a socket did not interrupt a SuperSpeed device in it. That is
why `SocketMap` sets every identity: either half alone is wrong for half the
devices that could be plugged in.

### Reading a port is expensive on a suspended hub

Measured per `states()` call:

```
3-1      2.0 ms        4-1      1.8 ms
3-1.3  273.2 ms        4-1.3    1.6 ms
```

`3-1.3` is runtime-suspended, and reading a port's `disable` attribute is a USB
control transfer that wakes it first — 75-220 ms per port. The whole socket map
cost **2.3 s** per read at first, which is unusable for a dashboard poll.

Three changes, in order of how much they bought:

1. Read each identity once per request instead of a whole hub per identity
   (`port_state` alongside `states`): 2.3 s → 0.9 s.
2. Cache the `enabled` reading with a 5 s TTL, invalidated on every write, since
   that read reports only *our own* switch state: 0.9 s → 0.4 ms warm.
3. While the hub stays suspended, keep trusting the cache past the TTL (300 s
   backstop). A suspended hub cannot have changed its own port power — a plug
   into a powered port resumes it, and a plug into an unpowered one is not
   detected at all. Steady state is now **~2 ms**, with one 0.9 s read at
   start-up.

Device presence is deliberately **not** cached: those attributes are populated
at enumeration and read in microseconds, and a stale "is something plugged in"
is the kind of lie that made the old debug page untrustworthy. Keeping the hub
awake would also have fixed the latency, at the cost of standby current — the
wrong trade on a battery.

## Verified, and what is still untested

Write path, 2026-10-18, through the root service: `POST /api/hub/4-1/port`
disabled a port and reported `active_ports: [2,3,4]`; restoring it brought it
back. `POST /api/socket {"socket":"7","on":false}` switched both identities and
the device disappeared and returned. `POST /api/socket/exclusive {"socket":"7"}`
left sockets 1-6 disabled and 7 powered, confirmed in sysfs. Every guard answers
correctly — 409 on a cascade socket, on an `exclusive` that would cut one and on
`all-off`; 404 on an unknown socket; 400 on a bad body or malformed JSON; 409
`no_socket_map` when no map exists; and turning a protected port *on* is allowed.

Untested: whether disabling a port actually removes VBUS. `ppps` is a claim.
Measure the current, or watch an LED-bearing device die, before relying on it
for power saving.

## Rewiring runbook

Written 2026-10-18 for the move off the Coolgear. The ordering is the point:
**make WiFi carry the WAN before the Coolgear is unplugged**, because the live
uplink (`eth1`, Coolgear port 3) is also the agent's only route out.

Arm the auto-revert watchdog first — `rv/raspap/wan_revert.sh`, documented in
`rv/raspap/README.txt`. It restores *some* uplink if a step leaves the RV dark,
and it outlives the SSH session that armed it.

```bash
cd rv/usbhub   && sudo ./setup_usbhub_api.sh          # 0.2.1 -> 0.3.0 FIRST:
                                                      # 0.3.0 carries the fix that
                                                      # stops a WAN switch cutting
                                                      # socket 7 (Bluetooth)
cd ../raspap   && sudo ./wan_revert.sh arm 120
```

1. **Edimax Bluetooth out of blue A, into the free black port.** Blue A is a
   SuperSpeed connector holding a 12 Mbit/s device; the Alfa wants it. Check
   `hciconfig` still lists `08:BE:AC:35:8E:5E` and
   `docker restart battery` if `bat2mqtt` went quiet — it binds one adapter by
   MAC with `gatttool` and does not recover from a disappearance on its own.
2. **Alfa from hub socket 1 into blue A.** Verify `wlan1` appears and the
   driver bound: `dmesg | tail` must show `ASIC revision` *and* a `phy`
   registration, not `failed with error -110`.
3. **Prove WiFi works as an uplink without committing to it:**
   `nmcli connection up alfa-Decher-5g ifname wlan1` then
   `curl -4 --interface wlan1 -s -o /dev/null -w '%{http_code}\n' http://1.1.1.1/`.
   Interface-bound on purpose — `pi5connect.sh` v2.1 keeps the healthy `eth1`
   incumbent, so this tests the fallback without taking the route away.
   **Do not continue until this passes.**
4. **Unplug the Coolgear.** `eth1` disappears and pi5connect fails over to
   `wlan1` (it did exactly this, in reverse, at 18:18 on 2026-10-18). Confirm
   with `cat /run/pi5connect-wan`.
5. **Wired adapter into socket 2, then cellular into 3, then Starlink into 4** —
   one at a time, confirming each enumerates before the next:
   `curl -s 127.0.0.1:12347/api/sockets | python3 -m json.tool`.
6. **Record the roles** (socket 1 is cleared: WiFi is no longer on the hub):
   ```bash
   sudo ./map_sockets.py --set-role 1= --set-role 2=wired \
                         --set-role 3=cell --set-role 4=starlink
   ```
7. **Protect the Alfa's new port.** Put `usb2:1` in `USBHUB_PROTECTED` in
   `usbhub-api.service` and re-run the installer. It is *not* auto-protected:
   cascade detection only fires on ports with a hub behind them, and the whole
   point of moving the Alfa off the hub is that nothing here can cut it. The
   old `1-2:3,1-2:4` entries become dead paths and can go.
8. `cd ../docker && docker compose up -d --build webserver`
9. `sudo ./wan_revert.sh disarm`

Two things to expect afterwards:

- **Interface names.** With several sockets powered at once, the three
  USB-ethernet adapters enumerate together and take `eth1`/`eth2`/`eth3` in
  arrival order — there is no `enx*` naming on this host (the policy is masked
  by symlinks to `/dev/null`). `Wired connection 1` is pinned to
  `connection.interface-name=eth1`, not to a MAC, so an adapter landing on
  `eth2` has no profile and NM must auto-create one. Once each adapter's MAC is
  known, pin them with `.link` files the way `11-wlan-wan.link` pins the Alfa.
  Exclusive WAN selection mostly hides this by powering one at a time.
- **The Alfa can no longer be power-gated by the hub**, so it draws its 400 mA
  whenever the Pi is on. `ip link set wlan1 down` on a WAN switch turns the
  radio off while keeping the device enumerated, which is the version of power
  saving that does not cost the fallback. Disabling `usb2:1` would also work
  and is exactly what step 7 forbids.

## Not yet done

- `server.py` still drives the Coolgear directly for the live path and assumes
  a single active port (`get_current_active_port()` returns one number). The
  proxy endpoints are written (`/api/hub/sockets`, `/api/hub/socket`,
  `/api/hub/socket/exclusive`, `/api/hub/wan`, `/api/hub/hubs`) and the debug
  and Internet pages use them, but the Coolgear selector is still the live one.
- Its `EXTENDED_CONNECTION_MAPPING` has `starlink` and `wired` both on
  Coolgear port 3, so one of them is wrong. Measured 2026-10-18: port 3 holds
  the `r8152` serving `192.168.2.197` from the house LAN — i.e. wired. The
  2026-10-17 sweep found Starlink (`206.214.239.194`, `192.168.100.1`) on that
  same port and recorded no MAC, so either the adapter or the cable moved
  between the two dates. Not resolvable from sysfs; the table dies with the
  Coolgear anyway, and `/api/hub/wan` selects by role.
- Roles are still unset (`"wan": {}` in the map) until step 6 above runs.
- The WAN devices are all still on the Coolgear, which is still the switch.
