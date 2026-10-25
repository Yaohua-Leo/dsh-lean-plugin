"""Probe the exact Lean MCP command/environment used by the preset.

The probe is deliberately bounded: a cache, DNS, startup, or stdio transport
failure must be reported as a real failure instead of leaving the caller
waiting forever.
"""

from lean_mcp_probe_common import (
    FORBIDDEN_TOOLS,
    REQUIRED_TOOLS,
    ProbeTimeout,
    StdioClient,
)


def main() -> int:
    client = StdioClient()
    try:
        init = client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "preset-probe", "version": "1"},
        })
        if "error" in init:
            print("initialize error:", init["error"])
            return 1
        print("serverInfo:", init.get("result", {}).get("serverInfo", {}))
        client.send("notifications/initialized", {}, notification=True)
        listing = client.request("tools/list", {})
        if "error" in listing:
            print("tools/list error:", listing["error"])
            return 1
        tools = listing.get("result", {}).get("tools", [])
        names = sorted(tool["name"] for tool in tools)
        missing = sorted(REQUIRED_TOOLS - set(names))
        forbidden = sorted(FORBIDDEN_TOOLS & set(names))
        print(f"tools ({len(names)}): {names}")
        if missing:
            print("MISSING required tools:", missing)
        if forbidden:
            print("FORBIDDEN tools still listed:", forbidden)
        if missing or forbidden:
            return 1
        print("\nOK: exact pinned preset tool surface is available")
        return 0
    except ProbeTimeout as exc:
        print("PROBE TIMEOUT/BLOCKED:", exc)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
