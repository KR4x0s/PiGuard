#!/usr/bin/python3
"""Root broker: only the installed gateway's five fixed commands are callable."""
import json
import os
from pathlib import Path
import grp
import re
import socketserver
import subprocess

ACTIONS = {"status", "check", "enable", "disable", "block"}
SOCKET = Path("/run/piguard-control.sock")
GATEWAY = "/usr/local/bin/piguard-gateway"


def power_state():
    try:
        result = subprocess.run(["/usr/bin/vcgencmd", "get_throttled"], capture_output=True,
                                text=True, timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else "Not available"
    except (OSError, subprocess.TimeoutExpired):
        return "Not available"


def power_ready(state=None):
    """A past soft-temperature event is advisory once no limit is active.

    Keep every other current or historical power/throttling flag blocking.
    In particular, an undervoltage event still requires operator attention.
    """
    state = power_state() if state is None else state
    match = re.fullmatch(r"throttled=0x([0-9a-fA-F]+)", state)
    return bool(match and int(match.group(1), 16) & ~0x80000 == 0)


def run_action(action):
    if action not in ACTIONS:
        return {"error": "unsupported_action", "client_path": "unverified"}
    if action == "enable" and not power_ready():
        return {"ok": False, "error": "power_unstable", "client_path": "unverified",
                "message": "Pi power/throttling must read 0x0 before enabling Tor."}
    try:
        result = subprocess.run([GATEWAY, action], capture_output=True, text=True,
                                timeout=160 if action in {"enable", "disable", "block"} else 15,
                                check=False)
        payload = result.stdout if result.returncode == 0 else result.stderr
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Invalid gateway result")
        data["ok"] = result.returncode == 0
        if action == "status":
            data["power"] = power_state()
            data["power_ok"] = power_ready(data["power"])
        return data
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"ok": False, "error": "gateway_unavailable", "client_path": "unverified"}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        request = self.rfile.readline(32).decode("ascii", errors="replace").strip()
        response = run_action(request)
        self.wfile.write((json.dumps(response) + "\n").encode())


def main():
    if os.geteuid() != 0:
        raise SystemExit("Broker must run as root")
    SOCKET.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam("piguard").gr_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    main()
