"""Read-only commissioning facts for the guided setup page."""
import json
from pathlib import Path
import re
import subprocess


def run(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def power_ready(power):
    match = re.fullmatch(r"throttled=0x([0-9a-fA-F]+)", power)
    return bool(match and int(match.group(1), 16) & ~0x80000 == 0)


def inspect():
    try:
        config = json.loads(Path('/etc/piguard-tor/gateway.json').read_text())
    except (OSError, ValueError):
        config = {}
    profile = config.get('profile') if config.get('profile') in {'home', 'travel'} else 'unknown'
    uplink_if = config.get('uplink') if config.get('uplink') in {'eth0', 'wlan0'} else 'wlan0'
    downstream_if = config.get('downlink') if config.get('downlink') in {'eth0', 'wlan0'} else 'eth0'
    try:
        addresses = json.loads(run("/usr/sbin/ip", "-j", "address", "show") or "[]")
        routes = json.loads(run("/usr/sbin/ip", "-j", "route", "show", "default") or "[]")
    except (ValueError, TypeError):
        addresses, routes = [], []
    by_name = {item.get("ifname"): item for item in addresses}
    def ipv4(name):
        return [f"{a['local']}/{a['prefixlen']}" for a in by_name.get(name, {}).get("addr_info", [])
                if a.get("family") == "inet" and "local" in a and "prefixlen" in a]
    uplink = ipv4(uplink_if)
    downstream = ipv4(downstream_if)
    route_ok = len(routes) == 1 and routes[0].get("dev") == uplink_if
    power = run("/usr/bin/vcgencmd", "get_throttled")
    return {
        "profile": profile, "uplink_if": uplink_if, "downstream_if": downstream_if,
        "uplink": uplink, "downstream": downstream,
        "downstream_ready": "10.78.0.1/24" in downstream,
        "route_ok": route_ok,
        "pihole_active": run("/usr/bin/systemctl", "is-active", "pihole-FTL.service") == "active",
        "tailscale_active": run("/usr/bin/systemctl", "is-active", "tailscaled.service") == "active",
        "power": power or "Not available", "power_ok": power_ready(power),
        "mac": run("/usr/bin/cat", f"/sys/class/net/{uplink_if}/address") or "Unavailable",
    }
