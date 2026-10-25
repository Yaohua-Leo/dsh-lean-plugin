#!/usr/bin/env python3
"""Probe a stdio MCP server: initialize, then tools/list.

The point is to assert that a server actually starts and exposes (or hides)
specific tool names, because a failed MCP startup is silent in most harnesses —
"no error" is not evidence that the tools exist.

Examples
--------
    python verify/probe_mcp.py --command "uvx lean-lsp-mcp" \
        --env LEAN_LOG_LEVEL=NONE --expect lean_local_search --forbid lean_build

    python verify/probe_mcp.py --harnesses --project D:/proj --home C:/Users/me
        # probes every command the installed configuration records

Exit codes: 0 all assertions held, 1 an assertion failed, 2 could not talk to
the server, 3 bad usage.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "lean-formalization-probe", "version": "1"}


class Server:
    """A stdio MCP server subprocess with line-delimited JSON-RPC."""

    def __init__(self, command: list[str], env: dict | None = None, cwd: str | None = None):
        merged = dict(os.environ)
        merged.update(env or {})
        self.lines: queue.Queue = queue.Queue()
        self.stderr: list[str] = []
        self.proc = subprocess.Popen(
            command, cwd=cwd, env=merged,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        self.next_id = 1

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip("\n"))
            if len(self.stderr) > 200:
                del self.stderr[0]

    def send(self, method: str, params: dict | None = None, notification: bool = False) -> int | None:
        assert self.proc.stdin is not None
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        ident = None
        if not notification:
            ident = self.next_id
            msg["id"] = ident
            self.next_id += 1
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return ident

    def wait_for(self, ident: int, timeout: float) -> dict:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("no response to request id %d within %.0fs" % (ident, timeout))
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("no response to request id %d within %.0fs" % (ident, timeout))
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers log to stdout on some platforms; not our answer
            if msg.get("id") == ident:
                return msg

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - best effort teardown
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


def probe(command: list[str], env: dict | None, timeout: float) -> dict:
    server = Server(command, env)
    result: dict = {"command": command, "env": {k: v for k, v in (env or {}).items()}}
    try:
        ident = server.send("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        init = server.wait_for(ident, timeout)
        if "error" in init:
            result.update(ok=False, stage="initialize", error=init["error"])
            return result
        result["serverInfo"] = init.get("result", {}).get("serverInfo")
        result["protocolVersion"] = init.get("result", {}).get("protocolVersion")
        server.send("notifications/initialized", {}, notification=True)

        ident = server.send("tools/list", {})
        listing = server.wait_for(ident, timeout)
        if "error" in listing:
            result.update(ok=False, stage="tools/list", error=listing["error"])
            return result
        tools = [t.get("name") for t in listing.get("result", {}).get("tools", [])]
        result.update(ok=True, tools=tools, toolCount=len(tools))
        return result
    except TimeoutError as exc:
        result.update(ok=False, stage="timeout", error=str(exc))
        return result
    finally:
        result["stderrTail"] = server.stderr[-6:]
        server.close()


def load_installer(args: argparse.Namespace):
    spec = importlib.util.spec_from_file_location("lf_install", REPO / "install" / "install.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module.Installer(argparse.Namespace(
        dry_run=True, home=args.home, project=args.project,
        dsh_home=args.dsh_home, agents_home=args.agents_home,
        scope="both", harnesses=None, include_unverified=False,
        no_project_gate=False, no_mcp=False, uv_cache_dir=None, uv_tool_dir=None,
        opencode_major=None, uninstall=False, doctor=False, strict=False,
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe_mcp.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--command", help="full command line of the server, e.g. 'uvx lean-lsp-mcp'")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--cwd")
    parser.add_argument("--expect", action="append", default=[], help="tool name that must be present")
    parser.add_argument("--forbid", action="append", default=[], help="tool name that must be absent")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json", action="store_true", help="print the raw probe result")
    parser.add_argument("--harnesses", action="store_true",
                        help="probe the commands the installed harness configuration records")
    parser.add_argument("--project", default=".")
    parser.add_argument("--home", default=None)
    parser.add_argument("--dsh-home", default=None)
    parser.add_argument("--agents-home", default=None)
    args = parser.parse_args(argv)

    targets: list[dict] = []
    if args.harnesses:
        installer = load_installer(args)
        extra_env = dict(kv.split("=", 1) for kv in args.env)
        for server_id in installer.mcp_servers_to_mount():
            # --env overrides the recorded env (a sandbox needs UV_CACHE_DIR/UV_TOOL_DIR,
            # and without this the documented workaround silently did nothing here).
            env = dict(installer.mcp_env(server_id))
            env.update(extra_env)
            targets.append({
                "name": server_id,
                "command": installer.mcp_command(server_id),
                "env": env,
                "expect": [t for t in installer.spec["mcp"]["servers"]["lean-lsp"]
                           ["disabledTools"].get("beam" if installer.beam_mode else "lspFallback", [])
                           if t.startswith("lean_local")] if server_id == "lean-lsp" else [],
                "forbid": installer.spec["mcp"]["servers"]["lean-lsp"]["disabledTools"]
                          ["beam" if installer.beam_mode else "lspFallback"] if server_id == "lean-lsp" else [],
            })
    elif args.command:
        targets.append({
            "name": "cli", "command": shlex.split(args.command),
            "env": dict(kv.split("=", 1) for kv in args.env),
            "expect": args.expect, "forbid": args.forbid,
        })
    else:
        parser.error("give either --command or --harnesses")

    failures = 0
    reports = []
    for target in targets:
        result = probe(target["command"], target.get("env"), args.timeout)
        tools = result.get("tools") or []
        missing = [t for t in target.get("expect", []) if t not in tools]
        present_forbidden = [t for t in target.get("forbid", []) if t in tools]
        ok = bool(result.get("ok")) and not missing and not present_forbidden
        result.update(name=target["name"], missing=missing, forbiddenPresent=present_forbidden, verdict=ok)
        reports.append(result)
        if not ok:
            failures += 1
        print("%-10s %-4s %-5s %s" % (
            target["name"], "OK" if ok else "FAIL",
            "%d" % len(tools) if result.get("ok") else "-",
            (result.get("serverInfo") or {}).get("name", result.get("stage", "")),
        ))
        if missing:
            print("            missing expected tools: %s" % ", ".join(missing))
        if present_forbidden:
            print("            forbidden tools present: %s" % ", ".join(present_forbidden))
        if not result.get("ok"):
            print("            error: %s" % result.get("error"))
            for line in result.get("stderrTail", [])[-4:]:
                print("            stderr: %s" % line)

    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("")
        for report in reports:
            if report.get("ok"):
                preview = ", ".join((report.get("tools") or [])[:8])
                print("%s: %d tools (%s%s)" % (
                    report["name"], report["toolCount"], preview,
                    ", ..." if report["toolCount"] > 8 else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
