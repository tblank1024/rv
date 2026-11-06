#!/usr/bin/env python3
"""Weekly Sophie restart + health report (stdlib only, read-only).

Writes markdown to reports/out/YYYY-MM-DD.md and reports/out/latest.md, prints it.
Usage: weekly_health_report.py [days=7] [--force]
Run daily: appends out/history.jsonl; writes the dated/latest report on Mondays or --force.
"""
import json, re, shutil, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
DAYS = int(args[0]) if args else 7
OUT = Path(__file__).parent / "out"
now = datetime.now().astimezone()
since = now - timedelta(days=DAYS)


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERR {e}"


def sh(s):
    return run(["bash", "-c", s])


def section(title, lines):
    return [f"## {title}", *(lines or ["none"]), ""]


rep = [f"# Sophie weekly report — {now:%Y-%m-%d %H:%M %Z}", f"Window: last {DAYS} days", ""]
flags = []

# --- host reboots / shutdowns
boots = []
for ln in run(["last", "-x", "-F", "reboot", "shutdown"]).splitlines():
    m = re.match(r"(reboot|shutdown)\s.*?(\w{3} \w{3}\s+\d+ [\d:]+ \d{4})", ln)
    if m:
        t = datetime.strptime(m.group(2), "%a %b %d %H:%M:%S %Y").astimezone()
        if t >= since:
            # a boot session ending "- crash" in wtmp did not shut down cleanly (power
            # loss, kernel panic, hardware watchdog); `sudo reboot`, the dashboard reboot
            # and systemctl reboot all write a shutdown record, so they count as planned.
            tag = " UNCLEAN (crash/power loss)" if m.group(1) == "reboot" and re.search(r"-\s+crash", ln) else ""
            boots.append(f"{t:%m-%d %H:%M} {m.group(1)}{tag}")
nboot = sum(" reboot" in b for b in boots)
nunclean = sum("UNCLEAN" in b for b in boots)
if nunclean: flags.append(f"{nunclean} UNPLANNED reboot(s)/crash")
def boots_near(t):
    return any(abs((t - datetime.strptime(b[:11], "%m-%d %H:%M").replace(year=t.year).astimezone()).total_seconds()) < 1800
               for b in boots if "reboot" in b)


rep += section(f"Host reboots ({nboot}; {nunclean} unclean; only unclean are flagged)", boots[:30])
rep += section("Uptime", [run(["uptime", "-p"])])

# --- docker containers
try:
    ids = run(["docker", "ps", "-aq"]).split()
    rows = []
    for c in json.loads(run(["docker", "inspect", *ids] ) or "[]"):
        name = c["Name"].lstrip("/")
        if not c["Config"].get("Labels", {}).get("com.docker.compose.project.working_dir", "").endswith("/rv/docker"):
            continue  # stale ad-hoc / foreign containers are noise
        h = c["State"].get("Health", {}).get("Status", "-")
        started = c["State"]["StartedAt"][:19]
        st = datetime.strptime(started, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
        rc, oom = c["RestartCount"], c["State"]["OOMKilled"]
        recent = st >= since
        rows.append(f"{name}: {c['State']['Status']}/{h} restarts={rc} oom={oom} started={st:%m-%d %H:%M}")
        if h not in ("healthy", "-") or oom or rc or c["State"]["Status"] != "running":
            flags.append(f"container {name} {c['State']['Status']}/{h} rc={rc} oom={oom}")
        elif recent and not boots_near(st):
            flags.append(f"container {name} (re)started {st:%m-%d %H:%M}")
    rep += section("Containers", rows)
    ev = run(["docker", "events", "--since", since.isoformat(), "--until", now.isoformat(),
              "--filter", "event=die", "--filter", "event=oom", "--filter", "event=restart",
              "--filter", "event=health_status", "--format", "{{.Time}} {{.Actor.Attributes.name}} {{.Action}}"], 60)
    evl = []
    for ln in ev.splitlines():
        p = ln.split(" ", 1)
        try:
            evl.append(f"{datetime.fromtimestamp(int(p[0])):%m-%d %H:%M} {p[1]}")
        except Exception:
            evl.append(ln)
    unhealthy = [e for e in evl if "unhealthy" in e or "oom" in e or " die" in e or "restart" in e]
    if unhealthy: flags.append(f"{len(unhealthy)} container die/restart/unhealthy/oom event(s)")
    rep += section(f"Container die/restart/oom/health events ({len(evl)}; shown: transitions)",
                   evl[-40:])
except Exception as e:
    rep += section("Containers", [f"ERR {e}"])

# --- systemd units
units = ["sophie-hostd", "wifi-api-rp5", "usbhub-api", "sophie-firewall", "pi5connect",
         "hostapd", "dnsmasq", "docker", "NetworkManager", "ssh", "wayvnc", "rpi-connect"]
ul = []
for u in units:
    o = run(["systemctl", "show", u, "-p", "ActiveState,SubState,NRestarts,Result"]).replace("\n", " ")
    if "ActiveState=" not in o or "LoadState=not-found" in o: continue
    ul.append(f"{u}: {o}")
    if "ActiveState=failed" in o or re.search(r"NRestarts=[1-9]", o):
        flags.append(f"unit {u}: {o}")
rep += section("Host units", ul)
failed = run(["systemctl", "--failed", "--no-legend", "--plain"])
if failed: flags.append("failed units present")
rep += section("systemctl --failed", failed.splitlines())
usr = run(["systemctl", "--user", "--failed", "--no-legend", "--plain"])
rep += section("user units failed", usr.splitlines())

# --- kernel / hardware
j = lambda pat, extra="": sh(f"journalctl -k --since '{since:%Y-%m-%d %H:%M}' --no-pager -g '{pat}' {extra} | tail -n 8")
hw = []
thr = run(["vcgencmd", "get_throttled"])
hw.append(thr)
if not thr.endswith("0x0"): flags.append(f"throttle flags {thr}")
hw.append(run(["vcgencmd", "measure_temp"]))
for label, pat in [("undervoltage", "Under-voltage|under-voltage"), ("oom-kill", "oom-kill|Out of memory"),
                   ("fs/io errors", "I/O error|EXT4-fs error|mmc.*error"), ("usb resets/disconnects", "usb .*(reset|disconnect)"),
                   ("CAN bus-off", "bus-off|can[01].*error"), ("watchdog", "watchdog.*(timeout|reset)")]:
    o = j(pat)
    n = 0 if "No entries" in o or not o else len(o.splitlines())
    hw.append(f"{label}: {n}" + (f"\n  {o.replace(chr(10), chr(10)+'  ')}" if n else ""))
    if n: flags.append(f"kernel {label}: {n}+ lines")
rep += section("Hardware / kernel", hw)

# --- resources
du = shutil.disk_usage("/")
pct = du.used * 100 // du.total
mem = sh("free -m | awk '/Mem/ {print $3\"/\"$2\" MB used\"}'")
res = [f"disk / {pct}% used ({du.free // 2**30} GB free)", f"mem {mem}", "load " + " ".join(open("/proc/loadavg").read().split()[:3])]
if pct > 85: flags.append(f"disk {pct}% full")
rep += section("Resources", res)

# --- network / security posture
net = [f"WAN: {sh('cat /run/pi5connect-wan')}", f"default route: {sh('ip route show default | head -2')}"]
try:
    import urllib.request
    fwj = json.load(urllib.request.urlopen("http://127.0.0.1:12348/api/firewall", timeout=10))["families"]
    for fam, v in fwj.items():
        if not v.get("reachable"):
            net.append(f"firewall {fam}: UNREADABLE {v.get('error','')[:80]}"); flags.append(f"firewall {fam} unreadable"); continue
        sp, cn = v["spec"], v["counts"]
        ok_in = "-j SOPHIE-IN" in (sp.get("INPUT") or "")
        ok_fwd = "SOPHIE-FWD" in (sp.get("FORWARD") or "") or "SOPHIE-FWD" in (sp.get("DOCKER-USER") or "")
        drop = next((l.split()[0] for l in (cn.get("SOPHIE-IN") or "").splitlines() if l.split()[2:3] == ["DROP"]), "?")
        net.append(f"firewall {fam}: INPUT->SOPHIE-IN {'yes' if ok_in else 'NO'}; FORWARD->SOPHIE-FWD {'yes' if ok_fwd else 'NO'}; "
                   f"uplink packets dropped (cumulative since rules loaded) {drop}")
        if not (ok_in and ok_fwd): flags.append(f"FIREWALL {fam} NOT ARMED")
except Exception as e:
    net.append(f"firewall: check failed ({type(e).__name__}: {e})"); flags.append("firewall check failed")
net.append("sshd failed logins: " + sh(f"journalctl -u ssh --since '{since:%Y-%m-%d %H:%M}' --no-pager -g 'Failed|Invalid user' | grep -vc '^-- '"))
rep += section("Network / security", net)

# --- watcher alerts via MQTT SYS_ERRORS (retained)
try:
    env = dict(l.split("=", 1) for l in Path(__file__).parent.parent.joinpath("docker/.env").read_text().splitlines() if "=" in l and not l.startswith("#"))
    u = next(v for k, v in env.items() if "MQTT" in k and "USER" in k)
    p = next(v for k, v in env.items() if "MQTT" in k and ("PASS" in k or "PW" in k))
    out = run(["docker", "exec", "mqtt", "mosquitto_sub", "-h", "localhost", "-u", u, "-P", p,
               "-t", "RVC/RV_Health/1", "-C", "1", "-W", "75"], 90)
    try:
        h = json.loads(out.strip().splitlines()[-1])
        if h.get("Status") != "OK" or not h.get("firewall_armed", 1):
            flags.append(f"RV_Health {h.get('Status')}: {str(h.get('detail',''))[:120]}")
    except Exception:
        flags.append("RV_Health unreadable/no message in 75 s (webserver health publisher down?)")
    rep += section("Latest RV_Health (published every 60 s; includes firewall_armed, container/unit state)", [out[:1200]])
except Exception as e:
    rep += section("MQTT health", [f"unavailable ({type(e).__name__})"])

# --- daily history: journald is RAM-only (36 h) to spare the SD card, so a 7-day kernel scan
# really only sees ~36 h. Run daily; each run appends ONE small line here (<1 KB/day of
# flash writes) so the weekly report can show the whole week.
OUT.mkdir(exist_ok=True)
HIST = OUT / "history.jsonl"
today = f"{now:%Y-%m-%d}"
entry = {"date": today, "flags": [f for f in flags if "(re)started" not in f]}
rows = []
if HIST.exists():
    rows = [json.loads(l) for l in HIST.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["date"] != today]
rows = (rows + [entry])[-28:]
HIST.write_text("".join(json.dumps(r) + "\n" for r in rows))
week = [r for r in rows if r["date"] >= f"{since:%Y-%m-%d}"]
hist_lines = [f"{r['date']}: " + ("; ".join(r["flags"]) or "ok") for r in week]
for r in week:
    for f in r["flags"]:
        if r["date"] != today and f not in flags:
            flags.append(f"{f} (on {r['date']})")
rep += section("Daily history (kernel/error flags per daily run)", hist_lines)

rep.insert(2, "**Flags:** " + ("; ".join(flags) if flags else "none — all clear") + "\n")
text = "\n".join(rep)
# Dated + latest reports are written on Mondays (or with --force); other days only update history.
if now.weekday() == 0 or "--force" in sys.argv:
    (OUT / f"{now:%Y-%m-%d}.md").write_text(text)
    (OUT / "latest.md").write_text(text)
    # keep only the 4 newest dated reports
    for old in sorted(OUT.glob("20??-??-??.md"))[:-4]:
        old.unlink()
print(text)
