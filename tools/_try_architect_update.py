"""Retry architect update with RavenColonialWeb auth headers (rcc-cmdr0 + rcc-key)."""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
ID64 = "16067875382777"
NEW_ARCHITECT = "Deric Bryant"


def load_api_key() -> str:
    cfg = Path(r"C:\Users\Drew\AppData\Local\EDMarketConnector\config.toml").read_text(
        encoding="utf-8"
    )
    m = re.search(r'ravencolonial_api_key\s*=\s*"([^"]+)"', cfg)
    if not m:
        raise SystemExit("No ravencolonial_api_key in config.toml")
    return m.group(1)


def rcc_cmdr0(name: str) -> str:
    return base64.b64encode(name.encode("utf-8")).decode("ascii")


def call(method: str, path: str, body=None, cmdr: str | None = None, key: str | None = None):
    headers = {"Accept": "application/json"}
    if cmdr and key:
        headers["rcc-cmdr0"] = rcc_cmdr0(cmdr)
        headers["rcc-key"] = key
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def main() -> None:
    key = load_api_key()
    cmdrs = ["Deric Bryant", "BNevyn", "Fenris Nihilus"]

    print("=== GET full system ===")
    print(call("GET", f"/api/v2/system/{ID64}")[:1200])

    print("\n=== GET architect ===")
    print(call("GET", f"/api/v2/system/{ID64}/architect"))

    body = {"update": [], "delete": [], "architect": NEW_ARCHITECT}

    for cmdr in cmdrs:
        print(f"\n=== PUT /sites as {cmdr!r} ===")
        status, text = call("PUT", f"/api/v2/system/{ID64}/sites", body, cmdr=cmdr, key=key)
        print(status, text[:800])

    print("\n=== GET architect after attempts ===")
    print(call("GET", f"/api/v2/system/{ID64}/architect"))

    print("\n=== API key owner probe (GET /fc/all) ===")
    for cmdr in ["Fenris Nihilus", "BNevyn", "Deric Bryant", "Deric bryant"]:
        status, text = call("GET", f"/api/cmdr/{urllib.parse.quote(cmdr)}/fc/all", cmdr=cmdr, key=key)
        print(f"{cmdr!r}: {status} {text[:120]}")


if __name__ == "__main__":
    main()

