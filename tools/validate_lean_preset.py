"""Validate the generated lean preset patch before installing it.

Checks what can be checked without the harness: YAML shape, the exact plugin
roster (the shipped `standard` preset's rows plus this preset's one MCP row), the
rendered persona text, and the MCP server configuration. Whether the packages
actually activate is decided by the preset registry at install time, and is
asserted afterwards through inspection.
"""
import sys
import json
from collections import Counter
from pathlib import Path
from lean_capabilities import read_spec, disabled_tools, runtime_policy

import yaml

# The shipped `standard` preset roster (packages/web-app/presets/standard.patch.yml).
STANDARD_NAMES = [
    "@deepseek-ai/dsh-persona",
    "@deepseek-ai/dsh-agent-instructions",
    "@deepseek-ai/dsh-time-context",
    "@deepseek-ai/dsh-tool-bash",
    "@deepseek-ai/dsh-tool-pwsh",
    "@deepseek-ai/dsh-tool-fs",
    "@deepseek-ai/dsh-tool-fs-search",
    "@deepseek-ai/dsh-tool-jobs",
    "@deepseek-ai/dsh-tool-schedule",
    "@deepseek-ai/dsh-skill-filesystem",
    "@deepseek-ai/dsh-tool-skill",
    "@deepseek-ai/dsh-command-goal",
    "@deepseek-ai/dsh-tool-goal",
    "@deepseek-ai/dsh-plan-mode",
    "@deepseek-ai/dsh-compaction-basic",
    "@deepseek-ai/dsh-command-compact",
    "@deepseek-ai/dsh-compaction-tool-result-pruner",
    "@deepseek-ai/dsh-tool-subagent-control",
    "@deepseek-ai/dsh-tool-subagent-control/list-agents",
    "@deepseek-ai/dsh-tool-subagent",
    "@deepseek-ai/dsh-tool-subagent",
    "@deepseek-ai/dsh-workflow-ptc",
    "@deepseek-ai/dsh-tool-workflow",
    "@deepseek-ai/dsh-tool-ask-user",
    "@deepseek-ai/dsh-tool-todo",
    "@deepseek-ai/dsh-tool-web",
    "@deepseek-ai/dsh-tool-present",
    "@deepseek-ai/dsh-plugin-manager/tools",
    "@deepseek-ai/dsh-plugin-market/tools",
]
SELFCHECK = "@local/dsh-lean-preset"
ADDED_LSP = ["@deepseek-ai/dsh-mcp-client", "@deepseek-ai/dsh-skill", SELFCHECK]
ADDED_BEAM = ["@deepseek-ai/dsh-mcp-client", "@deepseek-ai/dsh-mcp-client", "@deepseek-ai/dsh-skill", SELFCHECK]
GROUP = "cordis:group"



class JsExpr(str):
    """Sentinel for a !!js loader expression."""


def js_ctor(loader, node):
    return JsExpr(loader.construct_scalar(node))


yaml.SafeLoader.add_constructor("tag:yaml.org,2002:js", js_ctor)
yaml.SafeLoader.add_constructor("!js", js_ctor)


def walk(entries, problems, names):
    for row in entries:
        if not isinstance(row, dict):
            problems.append(f"row is not a mapping: {row!r}")
            continue
        name = row.get("name")
        if name == GROUP:
            if not isinstance(row.get("config"), list):
                problems.append(f"group {row.get('id')!r} has no nested entry list")
            else:
                walk(row["config"], problems, names)
            continue
        if not isinstance(name, str):
            problems.append(f"row {row.get('id')!r} has no plugin name")
            continue
        names.append(name)


def main() -> int:
    patch_path, expected_persona_path, persona_out_path = (Path(a) for a in sys.argv[1:4])
    problems: list[str] = []
    spec = read_spec()
    names: list[str] = []

    doc = yaml.load(patch_path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    if not isinstance(doc, list) or len(doc) != 1:
        raise SystemExit("patch must be a one-element list")
    layer = doc[0]
    if list(layer) != ["insert"]:
        problems.append(f"layer keys: {list(layer)}")
    rows = layer.get("insert") or []
    if len(rows) != 1:
        problems.append(f"expected exactly one inserted row, got {len(rows)}")
    row = rows[0]
    if row.get("id") != "preset-lean":
        problems.append(f"row id: {row.get('id')!r}")
    if row.get("name") != "@deepseek-ai/dsh-agent-preset":
        problems.append(f"row name: {row.get('name')!r}")

    cfg = row.get("config") or {}
    if cfg.get("id") != "lean":
        problems.append(f"config.id: {cfg.get('id')!r}")
    for key in ("name", "description", "order", "plugins"):
        if key not in cfg:
            problems.append(f"config missing {key}")
    if not isinstance(cfg.get("order"), int):
        problems.append(f"order is not an int: {cfg.get('order')!r}")
    if not isinstance(cfg.get("name"), str) or not cfg.get("name").strip():
        problems.append("display name is empty")
    if not isinstance(cfg.get("description"), str) or len(cfg.get("description", "")) < 20:
        problems.append("description is missing or too short")

    plugins = cfg.get("plugins") or []
    walk(plugins, problems, names)
    ids = [p.get("id") for p in plugins if isinstance(p, dict)]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate plugin ids: {ids}")

    persona = next((p for p in plugins if p.get("id") == "persona"), None)
    mode = "fallback"
    if persona is not None:
        prefix = (persona.get("config") or {}).get("prefix")
        if isinstance(prefix, str) and "MCP mode: `beam`" in prefix:
            mode = "beam"
    print(f"mode: {mode}")

    want = Counter(STANDARD_NAMES + (ADDED_BEAM if mode == "beam" else ADDED_LSP))
    got = Counter(names)
    if got != want:
        for name in sorted(set(want) | set(got)):
            if want[name] != got[name]:
                problems.append(f"roster mismatch for {name}: expected {want[name]}, got {got[name]}")

    if persona is None:
        problems.append("no persona row")
    else:
        prefix = (persona.get("config") or {}).get("prefix")
        if not isinstance(prefix, str):
            problems.append(f"persona prefix is {type(prefix).__name__}, not a string")
        elif prefix.strip() != expected_persona_path.read_text(encoding="utf-8").strip():
            problems.append("persona prefix does not match the rendered contract block")
        elif "propext" not in prefix or "sorry" not in prefix:
            problems.append("persona prefix is missing contract content")
        else:
            persona_out_path.write_text(prefix, encoding="utf-8", newline="\n")
            print(f"persona prefix OK: {len(prefix)} chars, {prefix.count(chr(10)) + 1} lines")

    mcp = next((p for p in plugins if p.get("id") == "mcp-lean-lsp"), None)
    if mcp is None:
        problems.append("no mcp-lean-lsp row")
    else:
        c = mcp.get("config") or {}
        if c.get("serverName") != "lean-lsp":
            problems.append(f"serverName: {c.get('serverName')!r}")
        if c.get("transport") != "stdio":
            problems.append(f"transport: {c.get('transport')!r}")
        command = str(c.get("command", ""))
        if not (
            command in {"uvx", "uvx.exe"}
            or "getBuiltinModule" in command
            or Path(command).is_file()
        ):
            problems.append(f"MCP command is not resolvable: {command!r}")
        if c.get("args") != spec["mcp"]["servers"]["lean-lsp"]["command"][1:]:
            problems.append(f"args: {c.get('args')!r}")
        env = c.get("env") or {}
        selected_mode = "beam" if mode == "beam" else "lsp-fallback"
        expected_disabled = ",".join(disabled_tools(spec, selected_mode))
        if env.get("LEAN_MCP_DISABLED_TOOLS") != expected_disabled:
            problems.append(f"disabled tools: {env.get('LEAN_MCP_DISABLED_TOOLS')!r}")
        if env.get("LEAN_LOG_LEVEL") != "NONE":
            problems.append(f"log level: {env!r}")
        if env.get("LEAN_MCP_MAX_OUTPUT_CHARS") != "12000":
            problems.append(f"max output chars: {env.get('LEAN_MCP_MAX_OUTPUT_CHARS')!r}")
        if c.get("toolCallTimeoutMs") != 300000:
            problems.append(f"timeout: {c.get('toolCallTimeoutMs')!r}")
        if c.get("failOnStartupError") is not True:
            problems.append("lean-lsp failOnStartupError must be true")

    beam_row = next((p for p in plugins if p.get("id") == "mcp-lean-beam"), None)
    if mode == "beam" and beam_row is None:
        problems.append("beam mode but no mcp-lean-beam row")
    if mode == "fallback" and beam_row is not None:
        problems.append("lsp-fallback mode must not mount mcp-lean-beam")
    if beam_row is not None and (beam_row.get("config") or {}).get("failOnStartupError") is not True:
        problems.append("lean-beam failOnStartupError must be true")

    skill_root = patch_path.parent / "skills"
    skill_group = next((p for p in plugins if p.get("id") == "lean-skills"), {})
    if (skill_group.get("name") != GROUP or skill_group.get("group") is not True
            or (skill_group.get("isolate") or {}).get("skills") is not True):
        problems.append("lean-skills must own a private skills registry realm")
    skill_rows = skill_group.get("config") or []
    if not isinstance(skill_rows, list):
        skill_rows = []
    if {p.get("id"): p.get("name") for p in skill_rows} != {
        "skill-registry": "@deepseek-ai/dsh-skill",
        "skill-filesystem": "@deepseek-ai/dsh-skill-filesystem",
        "tool-skill": "@deepseek-ai/dsh-tool-skill",
    }:
        problems.append("skill registry, provider and loader must share the isolated realm")
    skill_provider = next((p for p in skill_rows if p.get("id") == "skill-filesystem"), {})
    if (skill_provider.get("config") or {}).get("includeDefaultRoots") is not False:
        problems.append("skill-filesystem must isolate the preset from default skill roots")
    selected_mode = "beam" if mode == "beam" else "lsp-fallback"
    expected_skills = set(spec["mcp"]["capabilityProfiles"][selected_mode]["skills"])
    policy_path = patch_path.parent / "runtime-policy.json"
    try:
        if json.loads(policy_path.read_text(encoding="utf-8")) != runtime_policy(spec, selected_mode):
            problems.append("runtime policy differs from harnesses.json or the selected mode")
    except (OSError, ValueError):
        problems.append("runtime-policy.json is missing or invalid")
    actual_skills = {p.name for p in skill_root.iterdir()} if skill_root.is_dir() else set()
    if actual_skills != expected_skills:
        problems.append(f"packaged skills for {mode}: expected {expected_skills}, got {actual_skills}")
    for skill in expected_skills:
        if not (skill_root / skill / "SKILL.md").is_file():
            problems.append(f"packaged skill missing: {skill}")

    # The pruner threshold is a preset choice: diagnostics are the working
    # material, so the stock 8192 must not be in the generated patch.
    pruner = next((p for p in plugins if p.get("id") == "tool-result-pruner"), None)
    if pruner is not None:
        threshold = (pruner.get("config") or {}).get("thresholdChars")
        if threshold != 16384:
            problems.append(f"tool-result pruner thresholdChars: {threshold!r}")

    gated = {p.get("id"): str(p.get("disabled")) for p in plugins if isinstance(p, dict) and "disabled" in p}
    print("gated rows:", gated)
    print(f"roster: {sum(got.values())} plugin rows, {len([n for n in got if n == GROUP])} groups flattened")

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(" -", p)
        return 1
    print("\nOK: patch shape, roster, persona and MCP configuration validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
