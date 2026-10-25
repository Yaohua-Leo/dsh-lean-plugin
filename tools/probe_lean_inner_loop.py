"""Exercise outline, goal and diagnostics against a real Lean project.

The probe has a hard per-request timeout so startup or stdio transport
failures cannot leave the inner-loop acceptance job hanging.
"""

import sys

from lean_mcp_probe_common import ProbeTimeout, StdioClient, default_project


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    project = default_project()
    file_path = project / "Probe.lean"
    client = StdioClient()
    try:
        init = client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1"},
        })
        if "error" in init:
            print("initialize error:", init["error"])
            return 1
        client.send("notifications/initialized", {}, notification=True)
        results = []
        for name, args in [
            ("lean_file_outline", {"file_path": str(file_path)}),
            ("lean_goal", {"file_path": str(file_path), "line": 2, "column": 2}),
            ("lean_diagnostic_messages", {"file_path": str(file_path)}),
        ]:
            reply = client.request("tools/call", {"name": name, "arguments": args})
            if "error" in reply:
                print(f"{name}: JSON-RPC error={reply['error']}")
                results.append(False)
                continue
            result = reply.get("result", {})
            text = " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
            error = bool(result.get("isError"))
            print(f"{name}: isError={error} :: {text[:500]!r}")
            results.append(not error)
        return 0 if all(results) else 1
    except ProbeTimeout as exc:
        print("PROBE TIMEOUT/BLOCKED:", exc)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
