"""Check lean_local_search after the required file-based initialization call.

Each stdio request is bounded so a blocked uvx cache, DNS failure, or server
startup transport issue is surfaced as a diagnostic instead of a hung probe.
"""

from lean_mcp_probe_common import (
    ProbeTimeout,
    StdioClient,
    default_project,
)

QUERY = "probeLemma"


class Server:
    def __init__(self, with_local_bin: bool):
        self.client = StdioClient(with_local_bin=with_local_bin)
        init = self.client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1"},
        })
        if "error" in init:
            raise RuntimeError(f"initialize failed: {init['error']}")
        self.client.send("notifications/initialized", {}, notification=True)

    def request(self, method, params):
        return self.client.request(method, params)

    def close(self):
        self.client.close()


def call_search(with_local_bin: bool):
    project = default_project()
    file_path = project / "Probe.lean"
    label = "PATH with .local\\bin" if with_local_bin else "PATH without .local\\bin"
    server = None
    try:
        server = Server(with_local_bin)
        listing = server.request("tools/list", {})
        if "error" in listing:
            raise RuntimeError(f"{label}: tools/list failed: {listing['error']}")
        tools = listing.get("result", {}).get("tools", [])
        names = {tool["name"] for tool in tools}
        outline = server.request("tools/call", {
            "name": "lean_file_outline",
            "arguments": {"file_path": str(file_path)},
        })
        if outline.get("result", {}).get("isError"):
            raise SystemExit(f"{label}: file outline failed before search")
        schema = next(tool["inputSchema"] for tool in tools if tool["name"] == "lean_local_search")
        props = list((schema.get("properties") or {}).keys())
        args = {"query": QUERY, "project_root": str(project)}
        if "file_path" in props:
            args["file_path"] = str(file_path)
        args = {key: value for key, value in args.items() if key in props}
        reply = server.request("tools/call", {"name": "lean_local_search", "arguments": args})
        if "error" in reply:
            raise RuntimeError(f"{label}: tools/call failed: {reply['error']}")
        result = reply.get("result", {})
        text = " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        is_error = bool(result.get("isError"))
        print(f"\n[{label}] tools={len(names)} schema props={props}")
        print(f"[{label}] isError={is_error} len={len(text)}")
        print(f"[{label}] text[:600]={text[:600]!r}")
        return is_error, text
    except ProbeTimeout as exc:
        print(f"\n[{label}] PROBE TIMEOUT/BLOCKED: {exc}")
        return True, ""
    except RuntimeError as exc:
        print(f"\n[{label}] PROBE FAILED: {exc}")
        return True, ""
    finally:
        if server is not None:
            server.close()


def main() -> int:
    err_without, text_without = call_search(False)
    err_with, text_with = call_search(True)
    no_rg_observed = (
        "index" in text_without
        and any(status in text_without for status in ("unavailable", "warming", "ready"))
    )
    success = (not err_with) and QUERY in text_with and len(text_with) > 0
    print("\nSUMMARY")
    print(f"  without rg on PATH -> error={err_without}, fallback-index-observed={no_rg_observed}")
    print(f"  with rg on PATH    -> error={err_with}, mentions target={QUERY in text_with}")
    if not no_rg_observed or not success:
        print("FAIL: search did not show the expected fallback/success pair")
        return 1
    print("OK: file initialization and PATH-sensitive search behavior verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
