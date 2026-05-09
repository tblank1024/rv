#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
net_diag.py  --  RaspAP Bridge Network Diagnostics & Repair Tool
=================================================================
Diagnoses and fixes internet-routing problems on a Raspberry Pi 5
running RaspAP in bridge mode:
  * br0 = 10.0.0.1  (AP + wired LAN, bridged)
  * Internet uplinks: usb0 / eth1 / eth2 / wwan0 / ...

The most common failure: FORWARD chain has default DROP policy and
rules only exist for one uplink (e.g. usb0), but the active uplink
has changed (e.g. eth2).  This tool detects and fixes that.

Usage:
    sudo python3 net_diag.py           # full diagnosis + interactive menu
    sudo python3 net_diag.py --fix     # auto-apply all detected fixes
    sudo python3 net_diag.py --check   # diagnosis only (exit 1 if problems)
    sudo python3 net_diag.py --json    # dump state as JSON
"""

import argparse
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Force UTF-8 output (safe on all locales)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ----------------------------------------------------------------
# Colour helpers  (no external deps)
# ----------------------------------------------------------------
USE_COLOR = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def red(t):    return _c("31;1", t)
def green(t):  return _c("32;1", t)
def yellow(t): return _c("33;1", t)
def cyan(t):   return _c("36;1", t)
def bold(t):   return _c("1", t)
def dim(t):    return _c("2", t)

OK   = green(" [OK]  ")
FAIL = red(  " [!!]  ")
WARN = yellow(" [?]   ")
INFO = cyan(  " [i]   ")


def hdr(title: str):
    w = 64
    print()
    print(cyan("-" * w))
    print(cyan(f"  {title}"))
    print(cyan("-" * w))


# ----------------------------------------------------------------
# Shell helpers
# ----------------------------------------------------------------
def run(cmd: str, capture: bool = True) -> Tuple[int, str, str]:
    r = subprocess.run(
        cmd, shell=True, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def sudo(cmd: str, capture: bool = True) -> Tuple[int, str, str]:
    return run(f"sudo {cmd}", capture=capture)


# ----------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------
@dataclass
class Interface:
    name: str
    state: str
    addrs: List[str]
    master: Optional[str] = None


@dataclass
class Route:
    dest: str
    gateway: Optional[str]
    dev: str
    metric: int = 0


@dataclass
class ForwardRule:
    in_if: str
    out_if: str
    state_match: bool


@dataclass
class DiagState:
    interfaces: List[Interface] = field(default_factory=list)
    routes: List[Route] = field(default_factory=list)
    ip_forward: bool = False
    forward_rules: List[ForwardRule] = field(default_factory=list)
    nat_masq_lines: List[str] = field(default_factory=list)
    dns_ok: bool = False
    services: dict = field(default_factory=dict)
    bridge_iface: Optional[str] = None
    bridge_ip: Optional[str] = None
    internet_ifaces: List[str] = field(default_factory=list)
    default_gw_iface: Optional[str] = None
    problems: List[str] = field(default_factory=list)
    fixes_available: List[str] = field(default_factory=list)


# ----------------------------------------------------------------
# Data collection
# ----------------------------------------------------------------
def collect_interfaces() -> List[Interface]:
    _, out, _ = run("ip -j addr show 2>/dev/null")
    ifaces: List[Interface] = []
    try:
        data = json.loads(out)
        for d in data:
            name   = d.get("ifname", "")
            state  = d.get("operstate", "UNKNOWN")
            master = d.get("master")
            addrs  = [a["local"] for a in d.get("addr_info", []) if a.get("family") == "inet"]
            ifaces.append(Interface(name=name, state=state, addrs=addrs, master=master))
        return ifaces
    except (json.JSONDecodeError, KeyError):
        pass
    # Fallback: text parse
    _, out, _ = run("ip addr show")
    iface: Optional[Interface] = None
    for line in out.splitlines():
        m = re.match(r'^\d+: (\S+?)@?\S*:.*', line)
        if m:
            if iface:
                ifaces.append(iface)
            name   = m.group(1)
            state  = "UP" if "UP" in line else ("DOWN" if "DOWN" in line else "UNKNOWN")
            master_m = re.search(r'master (\S+)', line)
            iface = Interface(name=name, state=state, addrs=[],
                              master=master_m.group(1) if master_m else None)
        if iface and "inet " in line:
            am = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', line)
            if am:
                iface.addrs.append(am.group(1))
    if iface:
        ifaces.append(iface)
    return ifaces


def collect_routes() -> List[Route]:
    _, out, _ = run("ip route show")
    routes: List[Route] = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        dest, gw, dev, metric = parts[0], None, "", 0
        for i, p in enumerate(parts):
            if p == "via"    and i + 1 < len(parts): gw     = parts[i + 1]
            if p == "dev"    and i + 1 < len(parts): dev    = parts[i + 1]
            if p == "metric" and i + 1 < len(parts):
                try: metric = int(parts[i + 1])
                except ValueError: pass
        routes.append(Route(dest=dest, gateway=gw, dev=dev, metric=metric))
    return routes


def collect_forward_rules() -> List[ForwardRule]:
    _, out, _ = sudo("iptables -L FORWARD -n -v --line-numbers 2>/dev/null")
    rules: List[ForwardRule] = []
    for line in out.splitlines():
        # With -v the format is:
        # num  pkts bytes target prot opt in  out  source dest [extras]
        m = re.match(r'^\s*\d+\s+\S+\s+\S+\s+ACCEPT\s+\S+\s+--\s+(\S+)\s+(\S+)', line)
        if m:
            rules.append(ForwardRule(
                in_if=m.group(1), out_if=m.group(2),
                state_match="ESTABLISHED" in line,
            ))
    return rules


def collect_nat_masq() -> List[str]:
    _, out, _ = sudo("iptables -t nat -L POSTROUTING -n -v 2>/dev/null")
    return [l.strip() for l in out.splitlines() if "MASQUERADE" in l and "docker" not in l.lower()]


def check_dns() -> bool:
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo("google.com", 80)
        return True
    except OSError:
        return False


SERVICES_OF_INTEREST = [
    "dnsmasq", "hostapd", "dhcpcd", "systemd-networkd",
    "NetworkManager", "iptables", "netfilter-persistent",
]


def collect_services() -> dict:
    status = {}
    for svc in SERVICES_OF_INTEREST:
        _, out, _ = run(f"systemctl is-active {svc} 2>/dev/null")
        status[svc] = out.strip() or "inactive"
    return status


# ----------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------
BRIDGE_PREFIXES = ("10.0.0.",)


def is_bridge_ip(ip: str) -> bool:
    return any(ip.startswith(p) for p in BRIDGE_PREFIXES)


def looks_like_uplink(iface: Interface) -> bool:
    """Heuristic: UP, not a bridge member, not lo/docker/veth, has non-bridge IP."""
    if iface.state != "UP":
        return False
    if iface.name in ("lo", "docker0") or iface.name.startswith("veth"):
        return False
    if iface.master is not None:
        return False
    for addr in iface.addrs:
        if not is_bridge_ip(addr) and not addr.startswith("127.") and not addr.startswith("172.17."):
            return True
    return False


def build_diag() -> DiagState:
    ds = DiagState()
    ds.interfaces      = collect_interfaces()
    ds.routes          = collect_routes()
    ds.forward_rules   = collect_forward_rules()
    ds.nat_masq_lines  = collect_nat_masq()
    ds.services        = collect_services()
    ds.dns_ok          = check_dns()

    _, fwd_raw, _ = run("cat /proc/sys/net/ipv4/ip_forward")
    ds.ip_forward = fwd_raw.strip() == "1"

    for iface in ds.interfaces:
        for addr in iface.addrs:
            if is_bridge_ip(addr):
                ds.bridge_iface = iface.name
                ds.bridge_ip    = addr
                break

    for r in ds.routes:
        if r.dest == "default":
            ds.default_gw_iface = r.dev
            break

    for iface in ds.interfaces:
        if looks_like_uplink(iface):
            ds.internet_ifaces.append(iface.name)

    # ----- Problem detection -----
    if not ds.ip_forward:
        ds.problems.append("ip_forward_disabled")
        ds.fixes_available.append("enable_ip_forward")

    if ds.bridge_iface is None:
        ds.problems.append("no_bridge_found (expected br0 at 10.0.0.1)")

    br = ds.bridge_iface or "br0"

    for uplink in ds.internet_ifaces:
        out_ok = any(r.in_if == br     and r.out_if == uplink for r in ds.forward_rules)
        ret_ok = any(r.in_if == uplink and r.out_if == br     for r in ds.forward_rules)
        if not out_ok:
            ds.problems.append(f"missing FORWARD: {br} -> {uplink} (outbound)")
            ds.fixes_available.append(f"add_forward:{br}:{uplink}")
        if not ret_ok:
            ds.problems.append(f"missing FORWARD: {uplink} -> {br} (return)")
            ds.fixes_available.append(f"add_forward:{br}:{uplink}")

    if not ds.nat_masq_lines:
        ds.problems.append("no MASQUERADE rule (NAT not configured)")
        ds.fixes_available.append("add_masquerade")

    if not ds.dns_ok:
        ds.problems.append("DNS resolution failing from this host")

    return ds


# ----------------------------------------------------------------
# Display
# ----------------------------------------------------------------
def print_interfaces(ds: DiagState):
    hdr("Network Interfaces")
    for iface in ds.interfaces:
        if iface.name == "lo" or iface.name.startswith("veth"):
            continue
        sc  = green if iface.state == "UP" else red
        addrs  = ", ".join(iface.addrs) if iface.addrs else dim("(no IPv4)")
        master = dim(f" [member of {iface.master}]") if iface.master else ""
        uplink = green("  <-- internet uplink") if iface.name in ds.internet_ifaces else ""
        print(f"  {bold(iface.name):<18} {sc(iface.state):<20}  {addrs}{master}{uplink}")
    print()
    print(f"  Bridge iface   : {bold(ds.bridge_iface or red('NOT FOUND'))}")
    print(f"  Bridge IP      : {bold(ds.bridge_ip    or red('N/A'))}")
    print(f"  Uplinks found  : {bold(', '.join(ds.internet_ifaces) or yellow('none'))}")
    print(f"  Default GW dev : {bold(ds.default_gw_iface or red('none'))}")


def print_routes(ds: DiagState):
    hdr("Routing Table")
    for r in ds.routes:
        gw     = f"via {r.gateway:<18}" if r.gateway else " " * 24
        metric = dim(f"  metric {r.metric}") if r.metric else ""
        print(f"  {r.dest:<24} {gw}  dev {r.dev:<12}{metric}")


def print_forwarding(ds: DiagState):
    hdr("IP Forwarding & iptables FORWARD Chain")
    fwd_str = green("ENABLED") if ds.ip_forward else red("DISABLED  <-- PROBLEM")
    print(f"  IP forwarding  : {fwd_str}")

    print(f"\n  FORWARD ACCEPT rules ({len(ds.forward_rules)}):")
    if not ds.forward_rules:
        print(f"  {FAIL} No ACCEPT rules -- all forwarding is BLOCKED by default DROP policy")
    for r in ds.forward_rules:
        sm = dim("  (stateful)") if r.state_match else ""
        print(f"  {OK} {bold(r.in_if):<14} -> {bold(r.out_if):<14}{sm}")

    br = ds.bridge_iface or "br0"
    print(f"\n  Uplink coverage check (bridge = {bold(br)}):")
    if not ds.internet_ifaces:
        print(f"  {WARN} No internet uplinks detected to check.")
    for uplink in ds.internet_ifaces:
        out_ok = any(r.in_if == br     and r.out_if == uplink for r in ds.forward_rules)
        ret_ok = any(r.in_if == uplink and r.out_if == br     for r in ds.forward_rules)
        sym_o  = OK   if out_ok else FAIL
        sym_r  = OK   if ret_ok else FAIL
        col_o  = green("OK") if out_ok else red("MISSING -- internet won't work!")
        col_r  = green("OK") if ret_ok else red("MISSING -- replies dropped!")
        print(f"  {sym_o} {br} -> {uplink}  (outbound)  {col_o}")
        print(f"  {sym_r} {uplink} -> {br}  (return)    {col_r}")

    print(f"\n  MASQUERADE rules (POSTROUTING):")
    if ds.nat_masq_lines:
        for line in ds.nat_masq_lines:
            print(f"  {OK} {line}")
    else:
        print(f"  {FAIL} No MASQUERADE rules -- NAT not configured")


def print_services(ds: DiagState):
    hdr("Services")
    for svc, state in ds.services.items():
        if state == "active":
            sym, col = OK, green
        elif state == "inactive":
            sym, col = WARN, yellow
        else:
            sym, col = FAIL, red
        print(f"  {sym} {svc:<30} {col(state)}")


def print_dns(ds: DiagState):
    hdr("DNS / Internet Reachability")
    sym = OK if ds.dns_ok else FAIL
    msg = green("OK -- google.com resolves") if ds.dns_ok else red("FAILED -- cannot resolve google.com")
    print(f"  {sym} DNS: {msg}")


def print_problems(ds: DiagState):
    hdr("Problem Summary")
    if not ds.problems:
        print(f"  {OK} {green('No problems detected!')}")
        return
    for p in ds.problems:
        print(f"  {FAIL} {red(p)}")
    if ds.fixes_available:
        print(f"\n  {INFO} Run with --fix or use the menu (option 2) to repair.")


def run_full_diagnosis(ds: DiagState):
    print_interfaces(ds)
    print_routes(ds)
    print_forwarding(ds)
    print_services(ds)
    print_dns(ds)
    print_problems(ds)


# ----------------------------------------------------------------
# Fixes
# ----------------------------------------------------------------
def fix_ip_forward():
    print(f"  {INFO} Enabling IP forwarding ...")
    sudo("sysctl -w net.ipv4.ip_forward=1")
    _, cnt, _ = run("grep -c 'net.ipv4.ip_forward' /etc/sysctl.conf 2>/dev/null")
    if cnt.strip() == "0":
        sudo(r"bash -c 'echo net.ipv4.ip_forward=1 >> /etc/sysctl.conf'")
    else:
        sudo("sed -i 's/^#*net.ipv4.ip_forward.*/net.ipv4.ip_forward=1/' /etc/sysctl.conf")
    print(f"  {OK} IP forwarding enabled + persisted in /etc/sysctl.conf")


def fix_forward_rules(br: str, uplink: str, ds: DiagState):
    out_ok = any(r.in_if == br     and r.out_if == uplink for r in ds.forward_rules)
    ret_ok = any(r.in_if == uplink and r.out_if == br     for r in ds.forward_rules)
    changed = False
    if not out_ok:
        print(f"  {INFO} Adding FORWARD: {br} -> {uplink}  ACCEPT")
        sudo(f"iptables -I FORWARD -i {br} -o {uplink} -j ACCEPT")
        changed = True
    if not ret_ok:
        print(f"  {INFO} Adding FORWARD: {uplink} -> {br}  ACCEPT (stateful)")
        sudo(f"iptables -I FORWARD -i {uplink} -o {br} -m state --state RELATED,ESTABLISHED -j ACCEPT")
        changed = True
    if changed:
        print(f"  {OK} Forward rules for {uplink} added.")
    else:
        print(f"  {OK} Forward rules for {uplink} already present.")


def fix_masquerade(uplink: str = ""):
    if uplink:
        print(f"  {INFO} Adding MASQUERADE for {uplink} ...")
        sudo(f"iptables -t nat -A POSTROUTING -o {uplink} -j MASQUERADE")
    else:
        print(f"  {INFO} Adding broad MASQUERADE rule ...")
        sudo("iptables -t nat -A POSTROUTING ! -o lo -j MASQUERADE")
    print(f"  {OK} MASQUERADE rule added.")


def save_iptables():
    print(f"  {INFO} Saving iptables rules across reboots ...")
    if shutil.which("netfilter-persistent"):
        rc, _, err = sudo("netfilter-persistent save")
        if rc == 0:
            print(f"  {OK} Rules saved via netfilter-persistent.")
            return
        print(f"  {WARN} netfilter-persistent save failed: {err}")
    if os.path.exists("/etc/iptables"):
        sudo("sh -c 'iptables-save > /etc/iptables/rules.v4'")
        print(f"  {OK} Rules saved to /etc/iptables/rules.v4")
    else:
        print(f"  {WARN} Could not persist rules -- install iptables-persistent.")


def restart_service(name: str):
    print(f"  {INFO} Restarting {name} ...")
    rc, _, err = sudo(f"systemctl restart {name}")
    if rc == 0:
        print(f"  {OK} {name} restarted.")
    else:
        print(f"  {FAIL} {name} failed: {err[:120]}")


def apply_all_fixes(ds: DiagState):
    hdr("Applying All Detected Fixes")
    br = ds.bridge_iface or "br0"

    if "ip_forward_disabled" in ds.problems:
        fix_ip_forward()

    for uplink in ds.internet_ifaces:
        fix_forward_rules(br, uplink, ds)

    if not ds.nat_masq_lines:
        if ds.internet_ifaces:
            for uplink in ds.internet_ifaces:
                fix_masquerade(uplink)
        else:
            fix_masquerade()

    save_iptables()
    print(f"\n  {OK} Done.  Re-run diagnosis (option 1) to confirm all clear.")


# ----------------------------------------------------------------
# Switch / add internet uplink
# ----------------------------------------------------------------
def switch_uplink(ds: DiagState):
    hdr("Switch / Add Internet Uplink")
    br = ds.bridge_iface or "br0"

    candidates = [
        i for i in ds.interfaces
        if i.name not in ("lo", "docker0", br)
        and not i.name.startswith("veth")
        and i.master is None
    ]

    if not candidates:
        print(f"  {WARN} No candidate interfaces found.")
        return

    print("  Available interfaces:")
    for idx, iface in enumerate(candidates, 1):
        addrs   = ", ".join(iface.addrs) if iface.addrs else dim("(no IP)")
        cur_str = green("  <-- active uplink") if iface.name in ds.internet_ifaces else ""
        print(f"    {bold(str(idx))}.  {iface.name:<14} {iface.state:<8}  {addrs}{cur_str}")

    choice = input("\n  Enter number to enable FORWARD rules for (0 to cancel): ").strip()
    try:
        idx = int(choice)
        if idx == 0:
            return
        new_uplink = candidates[idx - 1].name
    except (ValueError, IndexError):
        print(f"  {FAIL} Invalid choice.")
        return

    fix_forward_rules(br, new_uplink, ds)

    # Offer to change default route
    _, def_out, _ = run(f"ip route show default dev {new_uplink} 2>/dev/null")
    if not def_out.strip():
        ans = input(f"  Set {new_uplink} as the default route? [y/N] ").strip().lower()
        if ans == "y":
            _, gw_out, _ = run(f"ip route show dev {new_uplink}")
            gw = None
            for line in gw_out.splitlines():
                m = re.search(r'via (\S+)', line)
                if m:
                    gw = m.group(1)
                    break
            if gw:
                sudo(f"ip route replace default via {gw} dev {new_uplink}")
                print(f"  {OK} Default route: via {gw} dev {new_uplink}")
            else:
                print(f"  {WARN} Could not determine gateway for {new_uplink}.")

    save_iptables()


# ----------------------------------------------------------------
# Show full iptables
# ----------------------------------------------------------------
def show_full_iptables():
    hdr("iptables -- filter table")
    _, out, _ = sudo("iptables -L -v -n --line-numbers 2>/dev/null")
    print(out)
    hdr("iptables -- nat table")
    _, out, _ = sudo("iptables -t nat -L -v -n --line-numbers 2>/dev/null")
    print(out)


# ----------------------------------------------------------------
# DHCP leases
# ----------------------------------------------------------------
def show_dhcp_leases():
    import datetime
    hdr("DHCP Leases")
    lease_files = [
        "/var/lib/misc/dnsmasq.leases",
        "/var/lib/dnsmasq/dnsmasq.leases",
    ]
    for f in lease_files:
        if os.path.exists(f):
            _, out, _ = run(f"cat {f}")
            print(f"  {bold(f)}:")
            if out.strip():
                print(f"\n  {'Expires':<14} {'MAC':<20} {'IP':<16} {'Hostname'}")
                print(f"  {'-'*60}")
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            exp = datetime.datetime.fromtimestamp(int(parts[0])).strftime("%m-%d %H:%M")
                        except Exception:
                            exp = parts[0]
                        print(f"  {exp:<14} {parts[1]:<20} {parts[2]:<16} {parts[3]}")
            else:
                print(f"  {dim('  (empty)')}")
            return
    print(f"  {WARN} No dnsmasq lease file found.")


# ----------------------------------------------------------------
# Interactive menu
# ----------------------------------------------------------------
MENU = [
    ("1", "Re-run full diagnosis"),
    ("2", "Apply all detected fixes automatically"),
    ("3", "Switch / add internet uplink (add FORWARD rules)"),
    ("4", "Show full iptables rules"),
    ("5", "Show DHCP leases"),
    ("6", "Save iptables rules (persist across reboots)"),
    ("7", "Restart dnsmasq"),
    ("8", "Restart hostapd"),
    ("9", "Restart networking (systemd-networkd + dhcpcd)"),
    ("q", "Quit"),
]


def interactive_menu(ds: DiagState):
    while True:
        hdr("Main Menu")
        for key, label in MENU:
            print(f"  {bold(key)}.  {label}")
        if ds.problems:
            print(f"\n  {WARN} {yellow(str(len(ds.problems)))} problem(s) detected -- choose 2 to fix.")

        choice = input("\n  Choice: ").strip().lower()

        if choice == "q":
            print(f"\n  {INFO} Goodbye.\n")
            break
        elif choice == "1":
            ds = build_diag()
            run_full_diagnosis(ds)
        elif choice == "2":
            apply_all_fixes(ds)
            ds = build_diag()
        elif choice == "3":
            switch_uplink(ds)
            ds = build_diag()
        elif choice == "4":
            show_full_iptables()
        elif choice == "5":
            show_dhcp_leases()
        elif choice == "6":
            save_iptables()
        elif choice == "7":
            restart_service("dnsmasq")
        elif choice == "8":
            restart_service("hostapd")
        elif choice == "9":
            restart_service("systemd-networkd")
            restart_service("dhcpcd")
        else:
            print(f"  {WARN} Unknown option.")


# ----------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------
def check_root():
    if os.geteuid() != 0:
        print(f"\n{WARN} Not running as root -- iptables output will be incomplete.")
        print(f"  Recommended: {bold('sudo python3 net_diag.py')}\n")


def main():
    parser = argparse.ArgumentParser(
        description="RaspAP Bridge Network Diagnostics & Repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              sudo python3 net_diag.py           # interactive
              sudo python3 net_diag.py --check   # diagnose only (exit 1 on problems)
              sudo python3 net_diag.py --fix     # auto-fix all problems
              sudo python3 net_diag.py --json    # dump state as JSON
        """),
    )
    parser.add_argument("--check", action="store_true", help="Diagnose only, no menu")
    parser.add_argument("--fix",   action="store_true", help="Auto-apply all detected fixes")
    parser.add_argument("--json",  action="store_true", help="Dump DiagState as JSON and exit")
    args = parser.parse_args()

    check_root()
    print(bold("\n  RaspAP Bridge -- Network Diagnostics & Repair"))
    print(dim("  " + "-" * 46))

    ds = build_diag()

    if args.json:
        import dataclasses
        print(json.dumps(dataclasses.asdict(ds), indent=2))
        return

    run_full_diagnosis(ds)

    if args.fix:
        apply_all_fixes(ds)
        return

    if args.check:
        sys.exit(1 if ds.problems else 0)

    interactive_menu(ds)


if __name__ == "__main__":
    main()
