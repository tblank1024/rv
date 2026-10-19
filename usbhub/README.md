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

## Verified, and what is still untested

Write path, 2026-10-18, through the root service (first privileged test):
`POST /api/hub/4-1/port {"port":1,"on":false}` disabled the port and reported
`active_ports: [2,3,4]`; restoring it brought it back. Every guard answers
correctly — 409 on a cascade socket, on an `exclusive` that would cut one and on
`all-off`; 404 on an unknown socket; 400 on a bad body or malformed JSON; 409
`no_socket_map` when no map exists; and turning a protected port *on* is allowed.

Untested: whether disabling a port actually removes VBUS. `ppps` is a claim.
Measure the current, or watch an LED-bearing device die, before relying on it
for power saving.

## Not yet done

- `server.py` still drives the Coolgear directly and assumes a single active
  port (`get_current_active_port()` returns one number). The proxy endpoints
  that would let the dashboard use this service are not written.
- The debug and Internet pages are therefore unchanged.
- The socket map is not built — it needs a device walked round the hub. Until
  then the WAN sockets have no names, and nothing can be wired to the UI.
- The WAN devices are all still on the Coolgear, which is still the switch.
  Nothing here touches it.
