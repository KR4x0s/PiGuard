"""Fixed-command JSON client for the root-owned PiGuard gateway broker."""
import json
import socket

ACTIONS = frozenset({"status", "check", "enable", "disable", "block"})
SOCKET = "/run/piguard-control.sock"


def invoke(action, path=SOCKET):
    if action not in ACTIONS:
        raise ValueError("Unsupported gateway action")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(180 if action in {"enable", "disable", "block"} else 20)
        client.connect(path)
        client.sendall((action + "\n").encode("ascii"))
        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > 16384:
                raise ValueError("Gateway reply too large")
    result = json.loads(b"".join(chunks))
    if not isinstance(result, dict):
        raise ValueError("Invalid gateway reply")
    return result
