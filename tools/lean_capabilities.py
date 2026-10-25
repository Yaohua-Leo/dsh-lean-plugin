"""Read the single mode/capability policy in harnesses.json.

No host probing or writes happen on import. The generated runtime policy is a
portable snapshot consumed by the installed DSH bundle.
"""
import copy
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def read_spec(repo: Path = REPO) -> dict:
    if not (repo / "harnesses.json").is_file() and (repo / "repo/harnesses.json").is_file():
        repo = repo / "repo"
    return json.loads((repo / "harnesses.json").read_text(encoding="utf-8"))


def disabled_tools(spec: dict, mode: str) -> list[str]:
    key = spec["mcp"]["capabilityProfiles"][mode]["disabledToolsKey"]
    return spec["mcp"]["servers"]["lean-lsp"]["disabledTools"][key]


def runtime_policy(spec: dict, mode: str) -> dict:
    profiles = copy.deepcopy(spec["mcp"]["capabilityProfiles"])
    if mode not in profiles:
        raise ValueError(f"unknown mode: {mode}")
    for name, profile in profiles.items():
        profile["forbiddenTools"] = {"lean-lsp": disabled_tools(spec, name), "lean-beam": []}
    return {
        "schemaVersion": 1,
        "mode": mode,
        "profiles": profiles,
        "leanLspPackage": spec["mcp"]["servers"]["lean-lsp"]["command"][1],
        "beamSourceCommit": spec["skills"]["beam"]["commit"],
        "beamSourceRepository": spec["skills"]["beam"]["repo"],
        "runtimeAcceptance": "A tool catalog is not a successful project sync or proof acceptance.",
    }
