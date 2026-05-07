#!/usr/bin/env python3
"""
fix_5g_routing.py  Diagnose and repair routing-table issues that prevent a
5G USB modem from providing internet access on a Raspberry Pi 5.

Usage:
    sudo python3 fix_5g_routing.py            # diagnose only
    sudo python3 fix_5g_routing.py --fix      # diagnose and apply fixes
    sudo python3 fix_5g_routing.py --verbose  # extra detail

Requirements: Python 3.7+, standard library only (subprocess, re, &).
"""

import argparse
import ipaddress
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional


# 
# Helpers
# 

def run(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run a command and return CompletedProcess.

    When *check* is False (the default) a non-zero exit code is silently
    ignored.  When *check* is True, CalledProcessError is raised on failure.
    """
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


def header(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print('='*60)


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def warn(msg: str) -> None:
    print(f"  [!!]  {msg}")


def info(msg: str) -> None:
    print(f"  [--]  {msg}")


# 
# Data structures
# 

@dataclass
class RouteEntry:
    destination: str   # e.g. "0.0.0.0" or "192.168.8.0"
    gateway: str       # e.g. "192.168.8.1" or "0.0.0.0"
    netmask: str       # e.g. "0.0.0.0" or "255.255.255.0"
    flags: str
    iface: str
    metric: int = 0


@dataclass
class InterfaceInfo:
    name: str
    up: bool = False
    has_ip: bool = False
    ipv4: Optional[str] = None
    prefix_len: int = 24       # actual prefix length from 'ip addr show'
    link_type: str = ""    # "wwan", "usb", "eth", "wlan", "other"
    bridge_master: Optional[str] = None  # set if this iface is enslaved to a bridge


C@dataclass
class DiagResult:
    modem_ifaces: List[InterfaceInfo] = field(default_factory=list)
    all_ifaces: List[InterfaceInfo] = field(default_factory=list)
    routes: List[RouteEntry] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)


# 
# Network interface discovery
# 

# Common interface name patterns for USB / 5G modems
MODEM_PATTERNS = re.compile(
    r'^(wwan\d+|usb\d+|wwp\w+|enx[0-9a-f]+|eth\d+|ppp\d+)$'
)

EXCLUDE_IFACES = {"lo"}


def get_interfaces(verbose: bool = False) -> List[InterfaceInfo]:
    """Return all non-loopback interfaces with basic state information."""
    result = run(["ip", "-o", "link", "show"])
    if result.returncode != 0:
        warn("Could not run 'ip link show'")
        return []

    ifaces: List[InterfaceInfo] = []
    # Format: <index>: <name>: <flags> &
    for line in result.stdout.splitlines():
        m = re.match(r'^\d+:\s+(\S+?)[@:]?\s+.*?<([^>]*)>', line)
        if not m:
            continue
        name = m.group(1).split('@')[0]  # strip @ifb0 etc.
        flags_str = m.group(2)
        if name in EXCLUDE_IFACES:
            continue

        up = "UP" in flags_str.split(',')

        # Determine link type
        if re.match(r'^wwan\d+|^wwp', name):
            link_type = "wwan"
        elif re.match(r'^usb\d+', name):
            link_type = "usb"
        elif re.match(r'^ppp\d+', name):
            link_type = "ppp"
        elif re.match(r'^eth\d+|^enx|^enp', name):
            link_type = "eth"
        elif re.match(r'^wlan\d+', name):
            link_type = "wlan"
        else:
            link_type = "other"

        iface = InterfaceInfo(name=name, up=up, link_type=link_type)

        # Detect bridge membership (master br* or any bridge master)
        master_m = re.search(r'master\s+(\S+)', line)
        if master_m:
            master_name = master_m.group(1)
            # Confirm the master is a bridge by checking its type
            master_type = run(["ip", "-o", "link", "show", master_name])
            if "bridge" in master_type.stdout or re.match(r'^br', master_name):
                iface.bridge_master = master_name

        # Get IPv4 address and prefix length
        addr_result = run(["ip", "-4", "addr", "show", name])
        addr_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', addr_result.stdout)
        if addr_match:
            iface.has_ip = True
            iface.ipv4 = addr_match.group(1)
            iface.prefix_len = int(addr_match.group(2))

        if verbose:
            bridge_info = f" bridge_master={iface.bridge_master}" if iface.bridge_master else ""
            info(f"Found interface: {name} up={up} ip={iface.ipv4} type={link_type}{bridge_info}")

        ifaces.append(iface)

    return ifaces


def identify_modem_ifaces(ifaces: List[InterfaceInfo]) -> List[InterfaceInfo]:
    """Return interfaces that look like they belong to a 5G/USB modem."""
    candidates = []
    for iface in ifaces:
        if iface.link_type in ("wwan", "usb", "ppp"):
            candidates.append(iface)
        elif iface.link_type == "eth" and MODEM_PATTERNS.match(iface.name):
            # Some modems present as ethernet (e.g. enx& CDC-Ethernet)
            candidates.append(iface)
    return candidates


# 
# Routing table inspection
# 

def get_routes(verbose: bool = False) -> List[RouteEntry]:
    """Parse the kernel routing table via 'route -n'."""
    result = run(["route", "-n"])
    if result.returncode != 0:
        # Fall back to 'ip route'
        return get_routes_ip(verbose)

    routes: List[RouteEntry] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        # Columns: Destination Gateway Netmask Flags Metric Ref Use Iface
        if len(parts) < 8 or not re.match(r'^\d', parts[0]):
            continue
        try:
            entry = RouteEntry(
                destination=parts[0],
                gateway=parts[1],
                netmask=parts[2],
                flags=parts[3],
                metric=int(parts[4]),
                iface=parts[7],
            )
            routes.append(entry)
            if verbose:
                info(f"Route: {entry.destination}/{entry.netmask} gw={entry.gateway} "
                     f"iface={entry.iface} flags={entry.flags} metric={entry.metric}")
        except (ValueError, IndexError):
            continue
    return routes


def get_routes_ip(verbose: bool = False) -> List[RouteEntry]:
    """Parse routing table via 'ip route show' (fallback)."""
    result = run(["ip", "route", "show"])
    routes: List[RouteEntry] = []
    for line in result.stdout.splitlines():
        # e.g. "default via 192.168.8.1 dev wwan0 proto dhcp metric 700"
        # or   "192.168.8.0/24 dev wwan0 proto kernel scope link src 192.168.8.100"
        dest = "0.0.0.0"
        gateway = "0.0.0.0"
        netmask = "0.0.0.0"
        iface = ""
        metric = 0
        flags = "U"

        if line.startswith("default"):
            dest = "0.0.0.0"
            netmask = "0.0.0.0"
            flags = "UG"
        else:
            prefix_m = re.match(r'^(\d+\.\d+\.\d+\.\d+)(?:/(\d+))?', line)
            if prefix_m:
                dest = prefix_m.group(1)
                prefix_len = int(prefix_m.group(2) or 32)
                netmask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").netmask)

        gw_m = re.search(r'via\s+(\d+\.\d+\.\d+\.\d+)', line)
        if gw_m:
            gateway = gw_m.group(1)
            flags = "UG"

        dev_m = re.search(r'dev\s+(\S+)', line)
        if dev_m:
            iface = dev_m.group(1)

        metric_m = re.search(r'metric\s+(\d+)', line)
        if metric_m:
            metric = int(metric_m.group(1))

        if iface:
            entry = RouteEntry(
                destination=dest,
                gateway=gateway,
                netmask=netmask,
                flags=flags,
                iface=iface,
                metric=metric,
            )
            routes.append(entry)
            if verbose:
                info(f"Route (ip): {dest}/{netmask} gw={gateway} "
                     f"iface={iface} flags={flags} metric={metric}")
    return routes


# 
# Diagnostics
# 

FALLBACK_DNS = "8.8.8.8"   # used for ping connectivity test

# Candidate paths where dhcpcd stores its lease/config files
_DHCPCD_LEASE_DIRS = ["/var/lib/dhcpcd", "/run/dhcpcd", "/var/lib/dhcp"]


def _gateway_from_dhcp_lease(iface_name: str) -> Optional[str]:
    """Try to read the gateway from a dhcpcd/dhclient lease file."""
    import glob as _glob
    patterns = [
        f"{d}/{iface_name}.lease*"   for d in _DHCPCD_LEASE_DIRS
    ] + [
        f"{d}/dhclient-{iface_name}.conf" for d in _DHCPCD_LEASE_DIRS
    ] + [
        "/var/lib/dhcp/dhclient.leases",
    ]
    for pattern in patterns:
        for path in _glob.glob(pattern):
            try:
                with open(path) as fh:
                    content = fh.read()
                m = re.search(r'routers?\s+(\d+\.\d+\.\d+\.\d+)', content)
                if m:
                    return m.group(1)
            except OSError:
                continue
    return None


def _gateway_from_ip_route(iface_name: str) -> Optional[str]:
    """Look for any gateway reachable via iface_name in 'ip route show'."""
    result = run(["ip", "route", "show", "dev", iface_name])
    for line in result.stdout.splitlines():
        m = re.search(r'via\s+(\d+\.\d+\.\d+\.\d+)', line)
        if m:
            return m.group(1)
    return None


def resolve_gateway(iface_obj: "InterfaceInfo") -> Optional[str]:
    """Return the best-guess gateway for *iface_obj*, or None if unknown.

    Priority:
    1. DHCP lease file (most accurate)
    2. Existing route via that interface that carries a 'via' gateway
    """
    gw = _gateway_from_dhcp_lease(iface_obj.name)
    if gw:
        return gw
    gw = _gateway_from_ip_route(iface_obj.name)
    if gw:
        return gw
    return None



def check_dns() -> bool:
    """Return True if DNS resolution appears to work.

    Uses Python's socket module to avoid locale-dependent tool output parsing.
    """
    import socket
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo("google.com", 80)
        return True
    except (socket.gaierror, OSError):
        return False


def ping_host(host: str, iface: Optional[str] = None, count: int = 3) -> bool:
    """Ping a host; optionally bind to a specific interface."""
    cmd = ["ping", "-c", str(count), "-W", "2"]
    if iface:
        cmd += ["-I", iface]
    cmd.append(host)
    result = run(cmd)
    return result.returncode == 0


def diagnose(verbose: bool = False) -> DiagResult:
    diag = DiagResult()

    #  1. Interfaces 
    header("1. Network Interfaces")
    all_ifaces = get_interfaces(verbose)
    modem_ifaces = identify_modem_ifaces(all_ifaces)
    diag.modem_ifaces = modem_ifaces
    diag.all_ifaces = all_ifaces

    # Show bridge interfaces with their IPs (these are the AP gateways)
    bridge_names = {i.bridge_master for i in all_ifaces if i.bridge_master}
    for br_name in sorted(bridge_names):
        br_addr = run(["ip", "-4", "addr", "show", br_name])
        br_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', br_addr.stdout)
        if br_match:
            ok(f"{br_name} (bridge/AP gateway) IP={br_match.group(1)}/{br_match.group(2)}")
        else:
            info(f"{br_name} (bridge) has no IP")

    if not modem_ifaces:
        warn("No modem-type interfaces (wwan*, usb*, ppp*) detected.")
        warn("If the modem is connected via USB, check 'lsusb' and 'dmesg | tail -30'.")
        diag.issues.append("no_modem_iface")
    else:
        for iface in modem_ifaces:
            state = "UP" if iface.up else "DOWN"
            ip_info = iface.ipv4 if iface.has_ip else "no IP"
            if iface.bridge_master:
                ok(f"{iface.name} is {state}, enslaved to bridge {iface.bridge_master} (no IP expected)")
            elif iface.up and iface.has_ip:
                ok(f"{iface.name} is {state}, IP={ip_info}")
            elif iface.up and not iface.has_ip:
                warn(f"{iface.name} is {state} but has NO IP address")
                diag.issues.append(f"no_ip:{iface.name}")
            else:
                warn(f"{iface.name} is {state}, IP={ip_info}")
                diag.issues.append(f"iface_down:{iface.name}")

    #  2. Routing table 
    header("2. Routing Table")
    routes = get_routes(verbose)
    diag.routes = routes

    default_routes = [r for r in routes if r.destination == "0.0.0.0"]
    modem_defaults = [
        r for r in default_routes
        if any(r.iface == iface.name for iface in modem_ifaces)
    ]

    if not default_routes:
        warn("No default (0.0.0.0) route found  internet traffic has nowhere to go!")
        diag.issues.append("no_default_route")
    elif not modem_defaults:
        others = [(r.iface, r.metric) for r in default_routes]
        warn(f"Default route exists but points to other interface(s): {others}")
        warn("Traffic is NOT routed through the 5G modem.")
        diag.issues.append("default_not_via_modem")
        for r in default_routes:
            info(f"  existing default: gw={r.gateway} dev={r.iface} metric={r.metric}")
    else:
        # Sort by metric; lowest metric wins
        best = sorted(modem_defaults, key=lambda r: r.metric)[0]
        all_defaults = sorted(default_routes, key=lambda r: r.metric)
        if all_defaults[0].iface != best.iface:
            warn(
                f"Modem default route (metric={best.metric}) is overridden by "
                f"{all_defaults[0].iface} (metric={all_defaults[0].metric})."
            )
            diag.issues.append("modem_route_metric_too_high")
            for r in all_defaults:
                info(f"  default: gw={r.gateway} dev={r.iface} metric={r.metric}")
        else:
            ok(f"Default route via modem interface {best.iface} (metric={best.metric}, gw={best.gateway})")

    #  3. Modem-specific subnet routes 
    header("3. Modem Subnet Routes")
    for iface in modem_ifaces:
        subnet_routes = [r for r in routes if r.iface == iface.name and r.destination != "0.0.0.0"]
        if subnet_routes:
            for r in subnet_routes:
                ok(f"  subnet {r.destination}/{r.netmask} dev {r.iface}")
        else:
            if iface.has_ip:
                warn(f"No subnet route for {iface.name} (IP={iface.ipv4})  may be missing.")
                diag.issues.append(f"no_subnet_route:{iface.name}")
            else:
                info(f"  {iface.name}: no IP, so no subnet route expected yet.")

    #  4. Connectivity test 
    header("4. Connectivity Tests")
    for iface in modem_ifaces:
        if iface.has_ip:
            if ping_host(FALLBACK_DNS, iface=iface.name):
                ok(f"Ping {FALLBACK_DNS} via {iface.name} succeeded")
            else:
                warn(f"Ping {FALLBACK_DNS} via {iface.name} FAILED")
                diag.issues.append(f"ping_failed:{iface.name}")

    if not modem_ifaces:
        info("Skipping connectivity test  no modem interface found.")
    else:
        # General (default-route) connectivity
        if ping_host(FALLBACK_DNS):
            ok(f"General ping {FALLBACK_DNS} (via default route) succeeded")
        else:
            warn(f"General ping {FALLBACK_DNS} FAILED  no internet connectivity")
            diag.issues.append("no_internet")

    #  5. DNS
    header("5. DNS Resolution")
    if check_dns():
        ok("DNS resolution working (google.com resolved)")
    else:
        warn("DNS resolution FAILED")
        diag.issues.append("dns_broken")

    #  6. Forwarding & NAT
    header("6. Forwarding & NAT (WiFi client internet access)")

    # 6a. IP forwarding
    fwd = run(["sysctl", "net.ipv4.ip_forward"])
    fwd_val = re.search(r'=\s*(\d+)', fwd.stdout)
    if fwd_val and fwd_val.group(1) == "1":
        ok("IP forwarding enabled (net.ipv4.ip_forward = 1)")
    else:
        val = fwd_val.group(1) if fwd_val else "unknown"
        warn(f"IP forwarding DISABLED (net.ipv4.ip_forward = {val})")
        diag.issues.append("ip_forward_disabled")

    # 6b. NAT MASQUERADE rules
    import os as _os
    _is_root = (_os.geteuid() == 0)
    if not _is_root:
        warn("Not running as root -- iptables checks may be incomplete. Re-run with sudo for accurate results.")

    nat = run(["iptables", "-t", "nat", "-L", "POSTROUTING", "-n", "-v"])
    modem_names = [i.name for i in modem_ifaces]
    masq_lines = [l for l in nat.stdout.splitlines() if "MASQUERADE" in l]
    masq_on_modem = [l for l in masq_lines if any(n in l for n in modem_names)]
    if masq_on_modem:
        for l in masq_on_modem:
            ok(f"NAT MASQUERADE rule found: {l.strip()}")
    elif masq_lines:
        warn("MASQUERADE rule exists but NOT on modem interface(s) -- wrong WAN interface?")
        for l in masq_lines:
            warn(f"  {l.strip()}")
        diag.issues.append("masquerade_wrong_iface")
    else:
        warn("No MASQUERADE rule found in nat POSTROUTING -- WiFi clients cannot reach internet")
        diag.issues.append("no_masquerade")

    # 6c. FORWARD chain rules
    # Traffic from WiFi clients arrives on the BRIDGE (br0), not on the bridge
    # member (wlan0). Rules must match br0; wlan0 rules will never fire.
    fwd_chain = run(["iptables", "-L", "FORWARD", "-n", "-v"])
    fwd_lines = [l for l in fwd_chain.stdout.splitlines()
                 if any(n in l for n in modem_names)]
    bridge_ifaces = list({i.bridge_master for i in all_ifaces if i.bridge_master})
    wlan_ifaces_names = [i.name for i in all_ifaces if i.link_type == "wlan"]
    # Prefer bridge interfaces; only fall back to bare wlan if not bridged
    unbridged_wlan = [n for n in wlan_ifaces_names
                      if not any(i.name == n and i.bridge_master for i in all_ifaces)]
    effective_ap_ifaces = bridge_ifaces + unbridged_wlan

    fwd_ap_to_modem = [l for l in fwd_lines if any(a in l for a in effective_ap_ifaces)]
    bridged_wlan_rules = [l for l in fwd_lines if any(n in l for n in wlan_ifaces_names)
                          and not any(a in l for a in effective_ap_ifaces)]

    if fwd_ap_to_modem:
        for l in fwd_ap_to_modem:
            ok(f"FORWARD rule found: {l.strip()}")
    else:
        if bridged_wlan_rules:
            warn("FORWARD rules use bridge member (wlan0) not the bridge (br0) -- these never match routed traffic:")
            for l in bridged_wlan_rules:
                warn(f"  {l.strip()}")
            diag.issues.append("no_forward_rules")
        elif fwd_lines:
            info("FORWARD rules reference modem interface but not AP/bridge interfaces:")
            for l in fwd_lines:
                info(f"  {l.strip()}")
        else:
            warn("No FORWARD rules found between AP/bridge and modem -- traffic will be dropped")
            diag.issues.append("no_forward_rules")
        if verbose:
            for l in fwd_chain.stdout.splitlines():
                info(f"  {l}")

    # 6d. FORWARD chain default policy and blocking rules
    fwd_policy_m = re.search(r'Chain FORWARD \(policy (\w+)', fwd_chain.stdout)
    if not fwd_policy_m and not _is_root:
        info("FORWARD chain policy unknown (needs root)")
    elif fwd_policy_m and fwd_policy_m.group(1) == "ACCEPT":
        ok("FORWARD chain default policy: ACCEPT")
    elif fwd_policy_m:
        warn(f"FORWARD chain default policy: {fwd_policy_m.group(1)} -- non-matching traffic is dropped")
        diag.issues.append("forward_policy_drop")

    drop_lines = [l for l in fwd_chain.stdout.splitlines()
                  if re.search(r'\b(DROP|REJECT)\b', l) and l.strip() and not l.startswith('Chain')]
    if drop_lines:
        warn(f"DROP/REJECT rules in FORWARD chain ({len(drop_lines)}) -- may block client traffic:")
        for l in drop_lines:
            warn(f"  {l.strip()}")
        diag.issues.append("forward_drop_rules")

    #  7. AP & Client Services
    header("7. AP & Client Services")

    # 7a. wlan interfaces
    wlan_ifaces = [i for i in all_ifaces if i.link_type == "wlan"]
    if not wlan_ifaces:
        warn("No wlan interfaces found -- is the wireless adapter present?")
        diag.issues.append("no_wlan_iface")
    else:
        for iface in wlan_ifaces:
            state = "UP" if iface.up else "DOWN"
            if iface.bridge_master:
                ok(f"{iface.name} is {state}, enslaved to bridge {iface.bridge_master} (no IP expected)")
            elif iface.up and iface.has_ip:
                ok(f"{iface.name} is {state}, IP={iface.ipv4}")
            elif iface.up:
                warn(f"{iface.name} is {state} but has no IP -- dnsmasq/hostapd may not be configured")
                diag.issues.append(f"wlan_no_ip:{iface.name}")
            else:
                warn(f"{iface.name} is {state}")
                diag.issues.append(f"wlan_down:{iface.name}")

    # 7b. hostapd
    hostapd = run(["systemctl", "is-active", "hostapd"])
    if hostapd.stdout.strip() == "active":
        ok("hostapd is running")
    else:
        warn(f"hostapd is {hostapd.stdout.strip()} -- no WiFi AP")
        diag.issues.append("hostapd_not_running")

    # 7c. dnsmasq
    dnsmasq = run(["systemctl", "is-active", "dnsmasq"])
    if dnsmasq.stdout.strip() == "active":
        ok("dnsmasq is running")
        leases = run(["cat", "/var/lib/misc/dnsmasq.leases"])
        lease_lines = [l for l in leases.stdout.splitlines() if l.strip()]
        if lease_lines:
            ok(f"DHCP leases active: {len(lease_lines)}")
            for l in lease_lines:
                info(f"  {l}")
        else:
            info("No active DHCP leases -- no clients connected, or lease file elsewhere")
    else:
        warn(f"dnsmasq is {dnsmasq.stdout.strip()} -- no DHCP/DNS for WiFi clients")
        diag.issues.append("dnsmasq_not_running")

    # 7d. Ping AP interface from Pi (sanity check that AP IP is reachable locally)
    for iface in wlan_ifaces:
        if iface.has_ip:
            if ping_host(iface.ipv4, count=1):
                ok(f"AP interface {iface.name} ({iface.ipv4}) is locally reachable")
            else:
                warn(f"AP interface {iface.name} ({iface.ipv4}) not reachable -- routing broken on AP side")
                diag.issues.append(f"ap_unreachable:{iface.name}")

    #  8. Packet Path (requires root)
    header("8. Packet Path")

    # 8a. iptables backend (legacy vs nf_tables)
    ipt_ver = run(["iptables", "--version"])
    ipt_backend = "nf_tables" if "nf_tables" in ipt_ver.stdout else "legacy"
    ok(f"iptables backend: {ipt_backend} ({ipt_ver.stdout.strip()})")
    nft_r = run(["nft", "list", "tables"])
    if nft_r.returncode == 0 and nft_r.stdout.strip():
        nft_tables = [l.strip() for l in nft_r.stdout.splitlines() if l.strip()]
        if ipt_backend == "legacy":
            warn(f"nftables is also active ({len(nft_tables)} tables) alongside legacy iptables -- rules may conflict")
            for t in nft_tables:
                info(f"  {t}")
            diag.issues.append("nftables_conflict")
        else:
            info(f"nftables tables: {', '.join(nft_tables)}")
    else:
        info("nftables not active or nft not installed")

    if _is_root:
        # 8b. iptables-save: full ruleset in one shot
        ipt_save = run(["iptables-save"])
        if ipt_save.returncode == 0:
            info("iptables-save output:")
            for l in ipt_save.stdout.splitlines():
                info(f"  {l}")
        else:
            # Fall back to per-chain dumps
            info("Full FORWARD chain:")
            for l in fwd_chain.stdout.splitlines():
                info(f"  {l}")
            info("Full nat POSTROUTING chain:")
            for l in nat.stdout.splitlines():
                info(f"  {l}")

        # 8c. Check FORWARD rule packet counters for br0 -> WAN rules
        # Non-zero counters mean real client traffic is being forwarded.
        fwd_save = run(["iptables", "-L", "FORWARD", "-n", "-v", "-x"])
        for br_name in sorted(bridge_names):
            wan_ifaces_check = [i.name for i in diag.modem_ifaces
                                if not i.bridge_master and i.has_ip]
            for wan in wan_ifaces_check:
                for line in fwd_save.stdout.splitlines():
                    if f" {br_name} " in line and f" {wan} " in line and "ACCEPT" in line:
                        pkt_m = re.match(r'\s*(\d+)\s+(\d+)', line)
                        if pkt_m:
                            pkts, bytes_ = int(pkt_m.group(1)), int(pkt_m.group(2))
                            if pkts > 0:
                                ok(f"FORWARD {br_name} -> {wan}: {pkts} packets ({bytes_} bytes) -- traffic is flowing")
                            else:
                                warn(f"FORWARD {br_name} -> {wan}: rule exists but 0 packets -- no client traffic seen yet")
    else:
        info("Skipping full chain dump and forward ping test (needs root)")

    return diag


# 
# Fixes
# 

def apply_fixes(diag: DiagResult, dry_run: bool = False) -> None:
    header("Applying Fixes")

    def exec_fix(description: str, cmd: List[str]) -> bool:
        print(f"  >> {' '.join(cmd)}")
        if dry_run:
            info(f"  (dry-run) would run: {' '.join(cmd)}")
            diag.fixes_applied.append(f"[DRY-RUN] {description}")
            return True
        result = run(cmd)
        if result.returncode == 0:
            ok(description)
            diag.fixes_applied.append(description)
            return True
        else:
            warn(f"Fix FAILED: {description}")
            warn(f"  stderr: {result.stderr.strip()}")
            return False

    modem_iface_names = [i.name for i in diag.modem_ifaces]

    for issue in diag.issues:

        #  Interface is DOWN 
        if issue.startswith("iface_down:"):
            iface = issue.split(":", 1)[1]
            exec_fix(f"Bring up interface {iface}", ["ip", "link", "set", iface, "up"])

        #  Interface has no IP — try DHCP 
        elif issue.startswith("no_ip:"):
            iface_name = issue.split(":", 1)[1]
            iface_obj = next((i for i in diag.modem_ifaces if i.name == iface_name), None)
            if iface_obj and iface_obj.bridge_master:
                info(f"  {iface_name} is a bridge slave ({iface_obj.bridge_master}); skipping DHCP fix.")
            else:
                warn(f"Interface {iface_name} has no IP. Attempting DHCP (dhclient)…")
                exec_fix(
                    f"Request DHCP address on {iface_name}",
                    ["dhclient", "-v", iface_name],
                )

        #  No default route at all 
        elif issue == "no_default_route":
            for iface_name in modem_iface_names:
                iface_obj = next((i for i in diag.modem_ifaces if i.name == iface_name), None)
                if iface_obj and iface_obj.has_ip:
                    gateway = resolve_gateway(iface_obj)
                    if not gateway:
                        warn(
                            f"Cannot determine gateway for {iface_name}. "
                            "Check the modem's DHCP lease or APN settings."
                        )
                        continue
                    warn(f"Adding default route via {gateway} dev {iface_name} metric 600")
                    exec_fix(
                        f"Add default route via {iface_name}",
                        ["ip", "route", "add", "default", "via", gateway, "dev", iface_name, "metric", "600"],
                    )

        #  Default route exists but not via modem 
        elif issue == "default_not_via_modem":
            for iface_obj in diag.modem_ifaces:
                if iface_obj.has_ip:
                    gateway = resolve_gateway(iface_obj)
                    if not gateway:
                        warn(
                            f"Cannot determine gateway for {iface_obj.name}. "
                            "Check the modem's DHCP lease or APN settings."
                        )
                        continue
                    # Add modem default with a lower metric than existing routes
                    min_metric = min((r.metric for r in diag.routes if r.destination == "0.0.0.0"), default=100)
                    new_metric = max(0, min_metric - 10)
                    warn(
                        f"Adding modem default route via {gateway} dev {iface_obj.name} "
                        f"metric {new_metric} (lower than existing {min_metric})"
                    )
                    exec_fix(
                        f"Add preferred default route via {iface_obj.name}",
                        ["ip", "route", "add", "default", "via", gateway,
                         "dev", iface_obj.name, "metric", str(new_metric)],
                    )

        #  Modem default route has too-high metric 
        elif issue == "modem_route_metric_too_high":
            for iface_obj in diag.modem_ifaces:
                if iface_obj.has_ip:
                    existing = [
                        r for r in diag.routes
                        if r.destination == "0.0.0.0" and r.iface == iface_obj.name
                    ]
                    for r in existing:
                        # Lower its metric so it wins
                        new_metric = max(0, r.metric - 200)
                        exec_fix(
                            f"Change default route metric on {iface_obj.name} to {new_metric}",
                            ["ip", "route", "change", "default",
                             "via", r.gateway, "dev", iface_obj.name,
                             "metric", str(new_metric)],
                        )

        #  Missing subnet route 
        elif issue.startswith("no_subnet_route:"):
            iface_name = issue.split(":", 1)[1]
            iface_obj = next((i for i in diag.modem_ifaces if i.name == iface_name), None)
            if iface_obj and iface_obj.has_ip:
                try:
                    net = ipaddress.IPv4Interface(
                        f"{iface_obj.ipv4}/{iface_obj.prefix_len}"
                    ).network
                    exec_fix(
                        f"Add subnet route for {iface_obj.name}",
                        ["ip", "route", "add", str(net), "dev", iface_obj.name],
                    )
                except Exception as exc:
                    warn(f"Could not add subnet route: {exc}")

        #  DNS broken
        elif issue == "dns_broken":
            info("Checking /etc/resolv.conf &")
            try:
                with open("/etc/resolv.conf") as f:
                    content = f.read()
                info(f"/etc/resolv.conf:\n{content}")
            except OSError:
                warn("Could not read /etc/resolv.conf")

            if not dry_run:
                try:
                    with open("/etc/resolv.conf", "a") as f:
                        f.write(f"\n# added by fix_5g_routing.py\nnameserver {FALLBACK_DNS}\n")
                    ok(f"Appended nameserver {FALLBACK_DNS} to /etc/resolv.conf")
                    diag.fixes_applied.append(f"Added nameserver {FALLBACK_DNS}")
                except OSError as exc:
                    warn(f"Could not write /etc/resolv.conf: {exc}")
            else:
                info(f"[dry-run] would append 'nameserver {FALLBACK_DNS}' to /etc/resolv.conf")
                diag.fixes_applied.append(f"[DRY-RUN] Add nameserver {FALLBACK_DNS}")

        #  IP forwarding disabled
        elif issue == "ip_forward_disabled":
            exec_fix(
                "Enable IP forwarding",
                ["sysctl", "-w", "net.ipv4.ip_forward=1"],
            )

        #  No MASQUERADE rule or on wrong interface
        elif issue in ("no_masquerade", "masquerade_wrong_iface"):
            for iface_obj in diag.modem_ifaces:
                if iface_obj.bridge_master:
                    info(f"  Skipping MASQUERADE on {iface_obj.name} (bridge slave of {iface_obj.bridge_master})")
                    continue
                if not iface_obj.has_ip:
                    info(f"  Skipping MASQUERADE on {iface_obj.name} (no IP address)")
                    continue
                exec_fix(
                    f"Add NAT MASQUERADE rule for {iface_obj.name}",
                    ["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", iface_obj.name, "-j", "MASQUERADE"],
                )

        #  No FORWARD rules between AP/bridge and modem
        elif issue == "no_forward_rules":
            bridge_ifaces = list({i.bridge_master for i in diag.all_ifaces if i.bridge_master})
            unbridged_wlan = [i.name for i in diag.all_ifaces
                              if i.link_type == "wlan" and not i.bridge_master]
            # Use the bridge itself, not its members -- routed packets arrive on br0
            ap_ifaces = bridge_ifaces + unbridged_wlan
            if not ap_ifaces:
                warn("Cannot determine AP/bridge interface for FORWARD rules -- add manually.")
            else:
                wan_ifaces = [i.name for i in diag.modem_ifaces
                              if not i.bridge_master and i.has_ip]
                for ap in ap_ifaces:
                    for modem in wan_ifaces:
                        exec_fix(
                            f"Allow forwarding {ap} -> {modem}",
                            ["iptables", "-A", "FORWARD", "-i", ap, "-o", modem, "-j", "ACCEPT"],
                        )
                        exec_fix(
                            f"Allow forwarding {modem} -> {ap} (established)",
                            ["iptables", "-A", "FORWARD", "-i", modem, "-o", ap,
                             "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
                        )
                if not wan_ifaces:
                    warn("No eligible WAN interface found for FORWARD rules (all modem ifaces are bridge slaves or have no IP)")


# 
# Summary
# 

def _modemmanager_has_modem() -> bool:
    """Return True if ModemManager is running and manages at least one modem."""
    r = run(["mmcli", "-m", "0"])
    return r.returncode == 0


def print_summary(diag: DiagResult) -> None:
    header("Summary")
    if not diag.issues:
        ok("No issues detected.")
        # Gateway reachability for each modem interface
        for iface in diag.modem_ifaces:
            if iface.has_ip and not iface.bridge_master:
                gw = _gateway_from_ip_route(iface.name)
                if gw:
                    if ping_host(gw, iface=iface.name, count=1):
                        ok(f"Gateway {gw} reachable via {iface.name}")
                    else:
                        warn(f"Gateway {gw} NOT reachable via {iface.name} -- check physical link or modem")
        # Only show mmcli hints if ModemManager actually has a modem
        if _modemmanager_has_modem():
            info("Modem APN settings  (mmcli -m 0)")
            info("SIM card status     (mmcli -m 0 --simple-status)")
    else:
        print(f"\n  Issues found ({len(diag.issues)}):")
        for issue in diag.issues:
            print(f"    {issue}")

    if diag.fixes_applied:
        print(f"\n  Fixes applied ({len(diag.fixes_applied)}):")
        for fix in diag.fixes_applied:
            print(f"     {fix}")

    print()


# 
# Entry point
# 

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose (and optionally fix) routing-table issues "
                    "preventing a 5G modem from providing internet on a Raspberry Pi 5."
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Attempt to apply fixes automatically (requires root)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what fixes would be applied without making changes."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print extra diagnostic detail."
    )
    args = parser.parse_args()

    print("5G Modem Routing Diagnostic Tool")
    print("Raspberry Pi 5    fix_5g_routing.py")

    if (args.fix or args.dry_run) and sys.platform != "win32":
        import os
        if os.geteuid() != 0:
            print("\nERROR: --fix and --dry-run require root privileges. Re-run with sudo.\n")
            return 1

    diag = diagnose(verbose=args.verbose)

    if args.fix or args.dry_run:
        apply_fixes(diag, dry_run=args.dry_run)

    elif diag.issues:
        print(
            "\n  Run with --fix to attempt automatic repairs, "
            "or --dry-run to preview them."
        )

    print_summary(diag)
    return 0 if not diag.issues else 2


if __name__ == "__main__":
    sys.exit(main())
