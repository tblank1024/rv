# Sophie weekly report — 2026-11-05 10:05 PST
Window: last 7 days
**Flags:** none — all clear


## Host reboots (4; 0 unclean; only unclean are flagged)
11-03 11:08 reboot
11-03 11:08 shutdown
11-03 10:38 reboot
11-03 10:37 shutdown
11-03 10:09 reboot
11-03 10:09 shutdown
11-03 09:48 reboot
11-03 09:47 shutdown

## Uptime
up 1 day, 22 hours, 56 minutes

## Containers
webserver: running/healthy restarts=0 oom=False started=11-03 11:08
watcher: running/healthy restarts=0 oom=False started=11-03 11:08
alarm: running/healthy restarts=0 oom=False started=11-03 11:08
solar: running/healthy restarts=0 oom=False started=11-03 11:08
tirelinc: running/healthy restarts=0 oom=False started=11-03 11:08
battery: running/healthy restarts=0 oom=False started=11-03 11:08
mqtt: running/healthy restarts=0 oom=False started=11-03 11:08
rvc2mqtt: running/healthy restarts=0 oom=False started=11-03 11:08
autoheal: running/healthy restarts=0 oom=False started=11-03 11:08

## Container die/restart/oom/health events (0; shown: transitions)
none

## Host units
sophie-hostd: Result=success NRestarts=0 ActiveState=active SubState=running
wifi-api-rp5: Result=success NRestarts=0 ActiveState=active SubState=running
usbhub-api: Result=success NRestarts=0 ActiveState=active SubState=running
sophie-firewall: Result=success NRestarts=0 ActiveState=active SubState=exited
pi5connect: Result=success NRestarts=0 ActiveState=inactive SubState=dead
hostapd: Result=success NRestarts=0 ActiveState=active SubState=running
dnsmasq: Result=success NRestarts=0 ActiveState=active SubState=running
docker: Result=success NRestarts=0 ActiveState=active SubState=running
NetworkManager: Result=success NRestarts=0 ActiveState=active SubState=running
ssh: Result=success NRestarts=0 ActiveState=active SubState=running
wayvnc: Result=success NRestarts=0 ActiveState=active SubState=running
rpi-connect: Result=success NRestarts=0 ActiveState=inactive SubState=dead

## systemctl --failed
none

## user units failed
none

## Hardware / kernel
throttled=0x0
temp=38.4'C
undervoltage: 0
oom-kill: 0
fs/io errors: 0
usb resets/disconnects: 0
CAN bus-off: 0
watchdog: 0

## Resources
disk / 52% used (48 GB free)
mem 1618/8063 MB used
load 0.27 0.14 0.10

## Network / security
WAN: eth1 192.168.2.1
default route: default via 192.168.2.1 dev eth1 
default via 192.168.2.1 dev eth1 proto dhcp src 192.168.2.178 metric 101
firewall v4: INPUT->SOPHIE-IN yes; FORWARD->SOPHIE-FWD yes; uplink packets dropped (cumulative since rules loaded) 484677
firewall v6: INPUT->SOPHIE-IN yes; FORWARD->SOPHIE-FWD yes; uplink packets dropped (cumulative since rules loaded) 193413
sshd failed logins: 0

## Latest RV_Health (published every 60 s; includes firewall_armed, container/unit state)
{"name": "RV_Health", "instance": 1, "timestamp": 1793901966, "Status": "OK", "firewall_armed": 1, "containers_unhealthy": 0, "containers_down": 0, "restarts_15m": 0, "units_failed": 0, "detail": "all clear"}
