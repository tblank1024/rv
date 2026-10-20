# usbhub — USB port power control

Per-port power control for the **Plugable** 7-in-1 powered hub, which selects the
RV's active uplink. (It replaced a Coolgear serial-controlled switch whose USB
control chip proved unstable.)

| File | Role |
|---|---|
| `usbhub_ports.py` | kernel per-port power (sysfs / `uhubctl`) |
| `usbhub_api.py` + `usbhub-api.service` | root HTTP/JSON on `127.0.0.1:12347` |
| `setup_usbhub_api.sh` | installs both into `/usr/local/sbin` |
| `map_sockets.py` | observes which physical socket is which (see below) |

## Why a root service

A plain powered hub has no control chip, so port power goes through the kernel,
and that is closed to the webserver container:

```
$ docker exec webserver grep ' /sys' /proc/mounts
sysfs /sys          rw
sysfs /sys/devices  ro        <- port attributes live under here
```

`/sys/bus/usb/devices/*` are symlinks into that read-only tree, so writing
`<hub>:1.0/<hub>-portN/disable` fails with `EACCES` even though the container is
privileged and uid 0 (verified 2026-10-18). Hence `usbhub-api.service`, the same
pattern as `wifi-api-rp5.service`: root, loopback, stdlib only, with the bind
address as the only access control. The alternative — making `/sys/devices`
writable in the container — runs against the direction the compose file already
sets ("privileged … document/trim in Phase 4 hardening").

## What "off" actually means

A disabled port is guaranteed to have **the device gone from the bus**. VBUS is
removed only if the hub really implements per-port power switching (the USB
LPSM field); hubs that gang their power, or that misreport, will drop the data
link while still feeding 5 V. `uhubctl` reports the claimed capability and the
API passes it through as `power_switching`, with `null` meaning *unknown* —
which is not the same as "no".

**If the point is saving power, confirm with a current measurement at the port.**
A device disappearing from `lsusb` is not evidence that it stopped drawing.

## Exclusivity is policy

A plain hub does not limit how many ports are on, so the two endpoints differ:

- `POST /api/hub/<hub>/port` — one port, others untouched, several may be on.
  For the **debug page**, where powering two at once is a diagnostic.
- `POST /api/hub/<hub>/exclusive` — power exactly one, switching the others off
  **first** so the hub never briefly feeds two WAN devices. For the **Internet
  page**, and the RV's normal policy: several WAN options may be *considered*,
  but only one is left drawing current.

`USBHUB_PROTECTED` ("hub:port", comma separated) refuses to switch a port off at
all. It is set in `usbhub-api.service`; see the comment there for what each
entry protects (the TPMS Bluetooth adapter and the hub's internal cascade).

**Ports carrying another hub are protected automatically**, so cascades never
have to be listed by hand: each hub's upstream port, and the Plugable's internal
cascade on both the USB 2 and USB 3 sides (`3-1:3`/`4-1:3` at last measurement).

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

The Plugable's four chips report `ppps` (per-port power switching) to `uhubctl`,
which is the capability claim — not proof VBUS drops. See the warning above.

The Pi 5's two blue ports each carry both speeds on one connector, so a USB 2
device and a USB 3 device on the same blue port share one connector. Moving
a device between ports can displace its neighbour: `bat2mqtt` pins its Bluetooth
adapter by MAC and does not recover when it disappears (`docker restart battery`).

Declared draw (`bMaxPower`) across the Pi's own ports can exceed the 600 mA
budget when `usb_max_current_enable=0` (raise to 1.6 A with a 27 W PSU).
`bMaxPower` is a declared ceiling, not consumption; watch `vcgencmd get_throttled`.

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

## Interface names

With several sockets powered at once, USB-ethernet adapters enumerate together
and take `eth1`/`eth2`/`eth3` in arrival order — there is no `enx*` naming on
this host (the policy is masked by symlinks to `/dev/null`). Pin each adapter
with a `.link` file by MAC the way `11-wlan-wan.link` pins the Alfa. Exclusive
WAN selection mostly hides this by powering one at a time. `pi5connect.sh`
ranks uplinks by socket role (`/etc/usbhub/sockets.json`), not by interface name.
