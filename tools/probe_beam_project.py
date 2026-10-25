"""Bounded Beam identity/project-sync probe; not proof or Desktop acceptance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from lean_capabilities import read_spec
from lean_mcp_probe_common import StdioClient


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rpc_result(reply):
    if not isinstance(reply, dict) or "error" in reply or not isinstance(reply.get("result"), dict):
        raise ValueError("MCP RPC failed or returned an invalid result")
    return reply["result"]


def call(client, name, arguments):
    result = rpc_result(client.request("tools/call", {"name": name, "arguments": arguments}))
    if result.get("isError") is True:
        raise ValueError(f"{name}: MCP tool reported an error; raw payload not persisted")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict) or not structured or "error" in structured:
        raise ValueError(f"{name}: missing or invalid structuredContent")
    return structured


def validate_identity(identity, expected_commit):
    if identity.get("name") != "lean-beam-mcp" or identity.get("source_commit") != expected_commit:
        raise ValueError("Beam identity/source commit differs from packaged skill pin")
    if identity.get("source_dirty") is True or identity.get("runtime_current") is False or identity.get("runtime_error"):
        raise ValueError("Beam reports dirty, stale or failed runtime identity")


def validate_sync(result, project, source):
    version = result.get("version")
    if type(version) is not int or version < 0:
        raise ValueError("lean_sync did not return a document version")
    path = result.get("path")
    if not isinstance(path, str) or (project / path).resolve() != source:
        raise ValueError("lean_sync returned a different source file")
    root = result.get("workspace", {}).get("root")
    if not isinstance(root, str) or Path(root).resolve() != project:
        raise ValueError("lean_sync returned a different workspace")
    readiness = result.get("readiness")
    counts = result.get("diagnostics", {}).get("counts")
    if not isinstance(readiness, dict) or type(readiness.get("save_ready")) is not bool or not isinstance(counts, dict):
        raise ValueError("lean_sync readiness/diagnostics are missing")
    return {"version": version, "saveReady": readiness["save_ready"],
            "blockingErrorCount": readiness.get("blocking_error_count"), "diagnosticCounts": counts}


def probe(project, probe_file, command, *, timeout=60, spec=None):
    spec = spec or read_spec()
    project = Path(project).resolve(strict=True)
    source = (project / probe_file).resolve(strict=True)
    if not source.is_relative_to(project) or source.suffix != ".lean":
        raise ValueError("probe file must be an existing .lean file inside project")
    if not (project / "lean-toolchain").is_file() or not any((project / n).is_file() for n in ("lakefile.lean", "lakefile.toml")):
        raise ValueError("project needs lean-toolchain and Lake configuration")
    executable = Path(shutil.which(command) or command).resolve(strict=True)
    if not executable.is_file():
        raise ValueError("Beam command must resolve to a file")
    inputs = {"source": source, "launcher": executable}
    for name in ("lean-toolchain", "lakefile.lean", "lakefile.toml", "lake-manifest.json", "lean-formalization.json"):
        if (project / name).is_file():
            inputs[name] = project / name
    before = {name: digest(path) for name, path in inputs.items()}
    client = StdioClient(timeout=timeout, server_command=[str(executable)], cwd=str(project), env=dict(os.environ))
    workspace = {"root": str(project)}
    opened = False
    try:
        init = rpc_result(client.request("initialize", {"protocolVersion": "2025-11-25",
            "capabilities": {}, "clientInfo": {"name": "lean-preset-project-probe", "version": "1.1.0"}}))
        if init.get("protocolVersion") != "2025-11-25":
            raise ValueError("Beam did not negotiate supported MCP protocol")
        client.send("notifications/initialized", notification=True)
        names, cursors, cursor = set(), set(), None
        for _ in range(10):
            page = rpc_result(client.request("tools/list", {"cursor": cursor} if cursor else {}))
            names.update(t["name"] for t in page.get("tools", []) if isinstance(t, dict) and isinstance(t.get("name"), str))
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if cursor in cursors:
                raise ValueError("Beam tools/list repeated a cursor")
            cursors.add(cursor)
        else:
            raise ValueError("Beam tool catalog exceeded pagination bound")
        required = set(spec["mcp"]["capabilityProfiles"]["beam"]["requiredTools"]["lean-beam"])
        if required - names:
            raise ValueError("Beam required tools missing: " + ", ".join(sorted(required - names)))
        validate_identity(call(client, "beam_version", {}), spec["skills"]["beam"]["commit"])
        opened = True
        sync = call(client, "lean_sync", {"workspace": workspace, "path": source.relative_to(project).as_posix()})
        observed = validate_sync(sync, project, source)
        validate_identity(call(client, "beam_version", {}), spec["skills"]["beam"]["commit"])
        call(client, "lean_drop_workspace", {"workspace": workspace})
        opened = False
        if {name: digest(path) for name, path in inputs.items()} != before:
            raise ValueError("project inputs or launcher changed during probe")
        return {"schemaVersion": 1, "status": "project-sync-compatible", "utc": datetime.now(timezone.utc).isoformat(),
                "project": str(project), "probeFile": source.relative_to(project).as_posix(),
                "beamCommand": str(executable), "beamSourceCommit": spec["skills"]["beam"]["commit"],
                "inputSha256": before, "observed": observed, "tools": sorted(names),
                "proofAcceptance": "unknown", "desktopAcceptance": "unknown"}
    finally:
        if opened:
            try:
                call(client, "lean_drop_workspace", {"workspace": workspace})
            except Exception:
                pass
        client.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True)
    p.add_argument("--probe-file", required=True)
    p.add_argument("--beam-command", required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=60)
    args = p.parse_args()
    try:
        result = probe(args.project, args.probe_file, args.beam_command, timeout=args.timeout)
        code = 0
    except Exception as error:
        # Never persist server stderr, source text or environment in a receipt.
        result = {"schemaVersion": 1, "status": "blocked", "errorType": type(error).__name__,
                  "proofAcceptance": "unknown", "desktopAcceptance": "unknown"}
        print(f"REFUSED: {type(error).__name__}; project sync was not accepted")
        code = 2
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['status']}: {args.receipt}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
