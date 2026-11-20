#!/usr/bin/python3
"""Verify one Tor request. Use gateway.py for gateway mode changes."""
import json
import subprocess

PROXY = "socks5h://127.0.0.1:9060"
CHECK_URL = "https://check.torproject.org/api/ip"


def run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          check=False)

def check_connection():
    # --disable is first: ignore ~/.curlrc. Override NO_PROXY even for '*'.
    # socks5h resolves destination names through Tor, never local DNS.
    result = run(["/usr/bin/curl", "--disable", "--silent", "--show-error", "--fail",
                  "--proxy", PROXY, "--noproxy", "", "--proto", "=https",
                  "--connect-timeout", "15", "--max-time", "45", CHECK_URL], timeout=50)
    if result.returncode:
        raise RuntimeError("Tor path check failed; no direct connection was attempted. "
                           "Check the service and bootstrap logs.")
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("Tor check returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("IsTor") is not True:
        raise RuntimeError("The check endpoint did not confirm a Tor exit.")
    return {"tor_path": "verified_for_this_request", "proxy": PROXY,
            "scope": "This check only; other apps and DNS paths are not verified."}

