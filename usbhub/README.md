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
all. It defaults to `1-2:4`, the Coolgear's own FT232R: cutting that is a loss
of *control*, not of internet, and the hub cannot then be steered back.

## Probing a new hub

Everything the repo cannot know — which hub is which, how many ports, what is
attached, whether power switching works — comes from one command:

```bash
sudo /usr/local/sbin/usbhub_ports.py      # human-readable
sudo uhubctl                              # per-port power switching support
curl -s http://127.0.0.1:12347/api/hubs   # same data as JSON
```

Measured 2026-10-18, before the Plugable was installed:

```
usb1  port 1  Edimax Bluetooth Adapter   500mA
usb1  port 2  USB2.1 Hub (Coolgear)      100mA
1-2   port 3  USB 10/100 LAN             100mA      <- the live WAN
1-2   port 4  FT232R USB UART             90mA      <- Coolgear control chip
usb3  port 2  ASUS USB-BT500             500mA
usb4  port 1  Wireless (Alfa MT7612U)    400mA
```

~1690 mA of *declared* draw against the 600 mA budget the Pi is running
(`usb_max_current_enable=0`, raise to 1.6 A with a 27 W PSU). `bMaxPower` is a
declared ceiling, not consumption, and `throttled=0x0` shows no undervoltage so
far — but note the two Bluetooth adapters claim more between them than the Alfa.

## Not yet done

- `server.py` still drives the Coolgear directly and assumes a single active
  port (`get_current_active_port()` returns one number). The proxy endpoints
  that would let the dashboard use this service are not written.
- The debug and Internet pages are therefore unchanged.
- The port → WAN-source mapping for the Plugable cannot be written until the
  probe runs on it. Keep the Coolgear live until then; nothing here touches it.
