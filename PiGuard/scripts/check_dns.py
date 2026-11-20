#!/usr/bin/env python3
"""Save explicit-server DNS evidence; this does not prove normal client routing."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", type=ipaddress.ip_address, help="Pi's IPv4 or IPv6 address")
    parser.add_argument("--output", type=Path, required=True, help="New JSON evidence file")
    args = parser.parse_args()
    if not shutil.which("dig"):
        parser.error("dig is required; on Raspberry Pi OS install dnsutils")
    if args.output.exists():
        parser.error("Output exists; use a new filename to preserve earlier evidence")
    checks = []
    for tcp in (False, True):
        for kind in ("A", "AAAA"):
            command = ["dig", "@" + str(args.server), "example.com", kind,
                       "+time=3", "+tries=1", "+noall", "+comments", "+answer", "+stats"]
            # Disable UDP-to-TCP fallback so each transport is tested separately.
            command.append("+tcp" if tcp else "+ignore")
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                stdout, stderr, code = result.stdout, result.stderr, result.returncode
            except subprocess.TimeoutExpired:
                stdout, stderr, code = "", "Probe exceeded 10 seconds", 124
            status = re.search(r"status: ([A-Z]+)", stdout)
            answers = re.findall(r"^\S+\s+\d+\s+IN\s+" + kind + r"\s+(\S+)", stdout, re.M)
            usable = False
            for answer in answers:
                try:
                    usable |= ipaddress.ip_address(answer).is_global
                except ValueError:
                    pass
            checks.append({"transport": "TCP" if tcp else "UDP", "type": kind,
                           "command": command, "exit_code": code,
                           "status": status.group(1) if status else None,
                           "answers": answers,
                           "passed": code == 0 and bool(status) and status.group(1) == "NOERROR" and usable,
                           "stdout": stdout, "stderr": stderr})
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
              "server": str(args.server), "checks": checks,
              "scope": "Explicit DNS resolution only. Blocking, normal client DNS use, and reboot persistence require separate checks."}
    # Exclusive creation avoids overwriting a prior result; DNS evidence is private.
    import os
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    for check in checks:
        print(f"{'PASS' if check['passed'] else 'FAIL'} {check['transport']} {check['type']}")
    print(f"Evidence: {args.output}")
    raise SystemExit(0 if all(check["passed"] for check in checks) else 1)


if __name__ == "__main__":
    main()
