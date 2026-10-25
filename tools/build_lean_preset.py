"""Render the lean-formalization agent preset patch.

Source of truth for the always-on rules is the upstream `contract.md`; this
script only indents it into the persona `prefix` block scalar and appends the
rows the preset mounts.

Usage:
  build_lean_preset.py <repo-dir> <bundle-dir> [--beam]

Without --beam the preset mounts lean-lsp in `lsp-fallback` mode (Lean Beam is
not installed). With --beam it mounts lean-beam as the proof-state server and
disables the lean-lsp tools Beam owns, following harnesses.json's beam mode.
"""
import json
import shutil
import sys
from pathlib import Path
from lean_capabilities import disabled_tools, runtime_policy

UVX = (
    "!!js \"process.getBuiltinModule('node:path').join("
    "process.env.USERPROFILE || process.env.HOME, '.local', 'bin', "
    "process.platform === 'win32' ? 'uvx.exe' : 'uvx')\""
)
BUNDLE_NAME = "@local/dsh-lean-preset"
# Resolve the skills beside this installed bundle. `baseUrl` is supplied by the
# DSH patch loader and works for both a local link and a profile-installed
# package; it also avoids confusing a custom DSH_HOME with ~/.dsh.
SKILL_DIRS = (
    "!!js \"process.getBuiltinModule('node:path').join("
    "process.getBuiltinModule('node:path').dirname("
    "process.getBuiltinModule('node:module').createRequire(baseUrl).resolve("
    "'" + BUNDLE_NAME + "')), 'skills')\""
)
RUNTIME_PATH = (
    "!!js \"process.getBuiltinModule('node:path').join("
    "process.env.USERPROFILE || process.env.HOME, '.local', 'bin') + "
    "process.getBuiltinModule('node:path').delimiter + (process.env.PATH || '')\""
)
# lean-beam-mcp is a native launcher on PATH, not a uvx package.
BEAM_COMMAND = "lean-beam-mcp"

TOOL_TIMEOUT_MS = 300000
BEAM_TIMEOUT_MS = 180000


IDENTITY = (
    "You are a Lean 4 formalization assistant powered by the {{model}} model. "
    "The rules below are always on: they hold in every workspace, even one whose "
    "own AGENTS.md was not loaded. Reply in the user's language (Chinese unless "
    "they write otherwise)."
)


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def instruction_block(contract_md: Path, beam: bool) -> str:
    body = strip_frontmatter(contract_md.read_text(encoding="utf-8"))
    head, _, _ = body.partition("## Project-specific rules (injected)")
    if beam:
        mode_line = (
            "- MCP mode: `beam`. Proof state, diagnostics, hover/definition/references and"
        )
        mode_line2 = (
            "  speculative probes belong to `mcp__lean-beam__*`; `lean-lsp` keeps the library"
        )
        mode_line3 = (
            "  search tools and has the Beam-owned tools disabled so exactly one server owns"
        )
        mode_line4 = "  each capability."
        beam_skill = (
            "- The `lean-beam` skill is mounted: `lean_run_at` probes a saved file WITHOUT"
        )
        beam_skill2 = (
            "  editing it, which is the cheap inner loop. A checkpoint (`lean_save`) never"
        )
        beam_skill3 = "  replaces the final clean build."
        project_rules = [
            "- One Beam runtime serves this preset: every Beam call names its workspace.",
            "- Acquire a document version with lean_sync/lean_update before a snapshot-bound",
            "  probe; do not reuse a proof handle after an edit or workspace restart.",
            "- Beam MCP owns its session; do not start a separate CLI serve owner.",
            "- lean-lsp retains library search and advisory analysis only. Its lean_verify",
            "  result is a pre-check, not a replacement for the project gate.",
            "- Pass project_root explicitly to lean_local_search; do not activate an LSP",
            "  proof-state tool just to select the search project.",
        ]
    else:
        mode_line = (
            "- Lean Beam is NOT enabled here: this is `lsp-fallback` mode, and the"
        )
        mode_line2 = (
            "  `lean-beam` skill is deliberately not mounted. Do not call Beam tools, and do"
        )
        mode_line3 = (
            "  not describe a Beam workflow as available."
        )
        mode_line4 = ""
        beam_skill = ""
        beam_skill2 = ""
        beam_skill3 = ""
        project_rules = [
            "- This preset mounts one shared `lean-lsp` server. Do not pursue two Lean",
            "  projects in parallel: finish or delegate one before switching, or the server",
            "  switches project under you.",
        ]
    rules = [
        "## Project-specific rules (injected)",
        "",
        "These rules add operating detail; nothing here weakens the non-negotiables above.",
        "",
        "- Read the workspace's `lean-formalization.json` before the first Lean call when",
        "  it exists: it records `mode`, `allowedAxioms`, `library`, `targets`,",
        "  `checkCommand` and `evidenceDir`. Do not infer the mode from which tools exist.",
        "- Axiom whitelist: `propext`, `Classical.choice`, `Quot.sound`",
        "  (`sorryAx` or any other axiom is a failure of the audit).",
    ]
    if not beam:
        rules += [
            "- Call a file-based tool (`lean_file_outline` or `lean_goal`) once before",
            "  `lean_local_search`: the server has no project root until such a call sets it.",
        ]
    rules += [
        "- Call lean_selfcheck before Lean work. The project mode must match this preset",
        "  revision. On a mode mismatch or backend failure, stop and explicitly select",
        "  another mode for a new session; never silently mix backend states.",
        "- If no `mcp__lean-lsp__*` tool appears in your catalog, say so and stop: the MCP",
        "  server did not start. Never emulate proof state, diagnostics or build results",
        "  with shell commands.",
        "- `lean_build` and `lean_run_code` are disabled here. Build through the shell",
        "  (`lake build`) and treat the project's `lake --no-cache build` plus axiom audit",
        "  as the only acceptance authority.",
        "- If `lean-formalization.json` is absent, the acceptance gate is not scaffolded in",
        "  that workspace: report `unknown` for acceptance instead of inferring success.",
        "  The gate scaffold lives in `%USERPROFILE%\\.lean-formalization\\repo`.",
        "- The gate is `scripts/leancheck.ps1` (build, axiom audit, locked statements,",
        "  library scan) and `scripts/leanstatus.ps1` reports what remains. Lock the",
        "  targets with `leancheck.ps1 -Lock` only after checking that the statements are",
        "  the ones wanted; re-locking to make a failing run pass is a change of target.",
        "- Progress is the statement DAG, not the `sorry` count: keep `coord/nodes.jsonl`",
        "  and read the derived queue with `scripts/leandag.ps1` (or `leandag.sh`). Do not",
        "  work on a node the targets do not need (a pruning candidate), and treat a node",
        "  whose declaration the scan shows resting on `sorryAx` as `hollow` no matter what",
        "  the file claims.",
    ]
    rules += project_rules
    rules += [
        mode_line,
        mode_line2,
        mode_line3,
    ]
    if mode_line4:
        rules.append(mode_line4)
    if beam_skill:
        rules += [beam_skill, beam_skill2, beam_skill3]
    block = IDENTITY + "\n\n" + head.rstrip() + "\n\n" + "\n".join(rules) + "\n"
    return block.strip("\n")


def indent_block(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join((pad + line) if line.strip() else "" for line in text.splitlines())


def mcp_rows(beam: bool, beam_command: str, spec: dict) -> str:
    """The Lean MCP rows of this preset, indented for the entry list."""
    startup_lsp = str(spec["mcp"]["servers"]["lean-lsp"]["failOnStartupError"]).lower()
    startup_beam = str(spec["mcp"]["servers"]["lean-beam"]["failOnStartupError"]).lower()
    package = spec["mcp"]["servers"]["lean-lsp"]["command"][1]
    disabled = ",".join(disabled_tools(spec, "beam" if beam else "lsp-fallback"))
    beam_command = beam_command.replace("'", "''")
    if beam:
        body = f"""\
# ── Lean capability (this preset's scope only) ──────────────────
# Lean Beam owns proof state, diagnostics and navigation; lean-lsp keeps the
# library-search tools with the Beam-owned tools disabled by name, so exactly one
# server owns each capability (harnesses.json `beam` mode). Lean Beam ships with a
# Lean distribution rather than as a uvx package, so the launcher is a command.
- id: mcp-lean-beam
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: lean-beam
    transport: stdio
    command: '{beam_command}'
    toolCallTimeoutMs: {BEAM_TIMEOUT_MS}
    failOnStartupError: {startup_beam}

# serverName lean-lsp => the tools appear as mcp__lean-lsp__lean_local_search etc.
# Resolve uvx in DSH's Node runtime; the package is pinned.
# The package is pinned: an
# unpinned uvx would silently change the tool surface this composition relies on.
- id: mcp-lean-lsp
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: lean-lsp
    transport: stdio
    command: {UVX}
    args:
      - '{package}'
    env:
      LEAN_LOG_LEVEL: 'NONE'
      LEAN_MCP_DISABLED_TOOLS: '{disabled}'
      # Per-field budget for goal states and diagnostics (server default 6000).
      LEAN_MCP_MAX_OUTPUT_CHARS: '12000'
      # The Desktop host does not inherit %USERPROFILE%\\.local\\bin, where uv/uvx
      # and rg live, so prepend it to the inherited PATH. Without this,
      # lean_local_search cannot find ripgrep.
      PATH: {RUNTIME_PATH}
    toolCallTimeoutMs: {TOOL_TIMEOUT_MS}
    failOnStartupError: {startup_lsp}
"""
    else:
        body = f"""\
# ── Lean capability (this preset's scope only) ──────────────────
# serverName lean-lsp => the tools appear as mcp__lean-lsp__lean_goal etc.
# Resolve uvx in DSH's Node runtime; the package is pinned.
# The package is pinned: an
# unpinned uvx would silently change the tool surface the disabled-tool list and
# this composition rely on.
- id: mcp-lean-lsp
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: lean-lsp
    transport: stdio
    command: {UVX}
    args:
      - '{package}'
    env:
      LEAN_LOG_LEVEL: 'NONE'
      LEAN_MCP_DISABLED_TOOLS: '{disabled}'
      # Per-field budget for goal states and diagnostics (server default 6000).
      LEAN_MCP_MAX_OUTPUT_CHARS: '12000'
      # The Desktop host does not inherit %USERPROFILE%\\.local\\bin, where uv/uvx
      # and rg live, so prepend it to the inherited PATH. Without this,
      # lean_local_search cannot find ripgrep.
      PATH: {RUNTIME_PATH}
    toolCallTimeoutMs: {TOOL_TIMEOUT_MS}
    failOnStartupError: {startup_lsp}
"""
    return indent_block(body, 10) + "\n"


def beam_command_from_argv(argv: list[str]) -> str:
    """`--beam-command <path-or-name>`: how the preset should launch lean-beam-mcp.

    A checkout install puts `lean-beam-mcp` on PATH; a Beam bundled into a Lean
    distribution lives in that toolchain's `bin` and is launched by absolute path
    (docs/TOOLCHAIN_BUNDLING.md), so the command has to be reachable from the
    harness process, not from a shell that resolved PATH differently.
    """
    if "--beam-command" in argv:
        idx = argv.index("--beam-command")
        if idx + 1 >= len(argv):
            raise SystemExit("--beam-command needs a value")
        return argv[idx + 1]
    return BEAM_COMMAND


def main() -> None:
    argv = sys.argv[1:]
    beam_command = beam_command_from_argv(argv)
    args = [a for a in argv if not a.startswith("--")]
    # --beam-command consumes the next token, which must not be read as a positional.
    if "--beam-command" in argv:
        idx = args.index(beam_command)
        del args[idx]
    beam = "--beam" in argv
    repo = Path(args[0])
    bundle = Path(args[1])
    block = instruction_block(repo / "contract.md", beam)
    prefix = indent_block(block, 16)
    spec = json.loads((repo / "harnesses.json").read_text(encoding="utf-8"))
    mcp = mcp_rows(beam, beam_command, spec)
    mode = "beam" if beam else "lsp-fallback"

    patch = f"""# Lean proof assistant preset ("lean") — MCP mode: {mode}.
#
# Generated by build_lean_preset.py from
# https://github.com/Yaohua-Leo/dsh-lean-plugin — do not hand-edit; change the
# generator or the upstream contract.md and reinstall the bundle.
#
# Composition: every row of the shipped `standard` preset, except that
#   1. the persona carries the lean-formalization contract (contract.md v1),
#   2. the skill provider scans only the skills packaged for this MCP mode, and
#   3. the `lean-lsp` MCP server is mounted in THIS preset's scope only, with
#      lean_build/lean_run_code disabled (the project's deterministic build and
#      axiom audit are the acceptance authority, not the model's).
- insert:
    - id: preset-lean
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: lean
        name: Lean证明助手
        description: Lean 4 形式化证明助手：lean-lsp 实时证明状态与数学库检索，构建/公理审计作为唯一验收门槛。
        order: 5
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              prefix: |-
{prefix}
          - id: agent-instructions
            name: '@deepseek-ai/dsh-agent-instructions'
            config:
              maxBytes: 65536
          - id: time-context
            name: '@deepseek-ai/dsh-time-context'
          - id: tool-bash
            name: '@deepseek-ai/dsh-tool-bash'
            disabled: !!js process.platform === 'win32'
          - id: tool-pwsh
            name: '@deepseek-ai/dsh-tool-pwsh'
            disabled: !!js process.platform !== 'win32'
          - id: tool-fs
            name: '@deepseek-ai/dsh-tool-fs'
          - id: tool-fs-search
            name: '@deepseek-ai/dsh-tool-fs-search'
            config:
              sampleOverCapGlobResults: false
          - id: tool-jobs
            name: '@deepseek-ai/dsh-tool-jobs'
          - id: tool-schedule
            name: '@deepseek-ai/dsh-tool-schedule'
          # Use a private registry as well as a restricted filesystem provider:
          # the host registry merges global/project contributions into a preset.
          # Keep provider and loader in the same realm so neither can see Beam
          # skills inherited from a host provider in fallback mode.
          - id: lean-skills
            name: cordis:group
            group: true
            isolate:
              skills: true
            config:
              - id: skill-registry
                name: '@deepseek-ai/dsh-skill'
              - id: skill-filesystem
                name: '@deepseek-ai/dsh-skill-filesystem'
                config:
                  includeDefaultRoots: false
                  customSkillDirs:
                    - {SKILL_DIRS}
              - id: tool-skill
                name: '@deepseek-ai/dsh-tool-skill'
          # Asserts this preset's own capability: which Lean MCP tools the session
          # can actually see and what the workspace gate says. Registered by this
          # bundle's index.js (only builtins/local imports; no @deepseek-ai imports).
          - id: lean-selfcheck
            name: '{BUNDLE_NAME}'
          - id: command-goal
            name: '@deepseek-ai/dsh-command-goal'
          - id: tool-goal
            name: '@deepseek-ai/dsh-tool-goal'
          - id: planning
            name: cordis:group
            group: true
            isolate:
              planMode: true
            config:
              - id: plan-mode
                name: '@deepseek-ai/dsh-plan-mode'
                config:
                  section: |
                    You are in plan mode. Stay in plan mode until the user approves your plan through exit_plan_mode or switches the session mode. Imperative language to implement changes means plan the implementation, not execute it. A user's conversational agreement — including an answer confirming something you asked — approves nothing and does not end plan mode; fold the confirmed decision into the plan and submit it through exit_plan_mode.

                    Explore first. Use non-mutating reads, searches, static analysis, and checks to ground the plan in the actual repository. Do not edit or write files, change configuration, run formatters or code generation that rewrites tracked files, commit, or otherwise carry out the plan. Prefer existing functions and patterns over new machinery.

                    The tool catalog stays the same across modes for request-cache stability. These plan-mode rules override any later tool description or guidance that suggests using mutation tools; those tools remain listed to keep the tool catalog unchanged. Do not use todo_write to track this planning phase: it tracks implementation after an approved plan, while the plan itself belongs in exit_plan_mode.

                    Resolve discoverable facts by inspection. Use ask_user_question only for user-owned choices or material ambiguity that inspection cannot answer. Do not ask the user where code lives or how current behavior works when you can find out.

                    Make the plan decision-complete: state the goal and success criteria; group implementation changes by subsystem; identify public API, schema, and data-flow changes; cover edge cases, failure modes, tests, acceptance criteria, and explicit assumptions. Keep it concise enough to review but detailed enough that another engineer can implement it without making design decisions.

                    When ready, call exit_plan_mode with the complete plan markdown, starting with a # title. Make exit_plan_mode the only and final tool call in that assistant response: it presents the plan for approval, and implementation begins only in a later step after approval. Do not paste the final plan as a plain reply or ask "should I proceed?" through prose or ask_user_question. If review rejects it, incorporate the feedback and present again. If the review channel is unavailable or aborted, stay in plan mode and ask the user to switch modes manually; do not proceed with implementation.
          - id: compaction
            name: cordis:group
            group: true
            isolate:
              compaction: true
              toolResultPruner: true
            config:
              - id: compaction-basic
                name: '@deepseek-ai/dsh-compaction-basic'
              - id: command-compact
                name: '@deepseek-ai/dsh-command-compact'
              - id: tool-result-pruner
                name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
                config:
                  # Lean diagnostics are the working material: the stock 8192
                  # threshold prunes the middle of a long diagnostic list exactly
                  # when compaction pressure is highest. Raise it, and let the MCP
                  # server keep more of each goal/diagnostic field as well.
                  thresholdChars: 16384
                  headChars: 8192
                  tailChars: 2048
          - id: delegation
            name: cordis:group
            group: true
            isolate:
              workflowEngine: true
            config:
              - id: tool-subagent-control
                name: '@deepseek-ai/dsh-tool-subagent-control'
              - id: tool-subagent-list-agents
                name: '@deepseek-ai/dsh-tool-subagent-control/list-agents'
              - id: tool-subagent
                name: '@deepseek-ai/dsh-tool-subagent'
                config:
                  provider: spawn
                  toolName: subagent
                  modelSelectionSettings: true
              - id: tool-subagent-fork
                name: '@deepseek-ai/dsh-tool-subagent'
                config:
                  provider: fork
                  toolName: subagent_fork
              - id: workflow-ptc
                name: '@deepseek-ai/dsh-workflow-ptc'
                config:
                  provider: spawn
              - id: tool-workflow
                name: '@deepseek-ai/dsh-tool-workflow'
{mcp}          - id: tool-ask-user
            name: '@deepseek-ai/dsh-tool-ask-user'
          - id: tool-todo
            name: '@deepseek-ai/dsh-tool-todo'
            config:
              allowParallelInProgress: true
          - id: tool-web
            name: '@deepseek-ai/dsh-tool-web'
            config:
              fetch: true
              searchTimeoutMs: 60000
          - id: present
            name: '@deepseek-ai/dsh-tool-present'
          - id: tool-plugin-manager
            name: '@deepseek-ai/dsh-plugin-manager/tools'
            disabled: true
          - id: tool-plugin-market
            name: '@deepseek-ai/dsh-plugin-market/tools'
            disabled: true
"""
    # A profile-installed bundle must carry the skills it advertises. Keep the
    # package copy generated from the repository's canonical skill sources so a
    # normal rebuild cannot leave stale or missing skill files behind.
    packaged_skills = bundle.resolve() / "skills"
    if packaged_skills.is_symlink() or packaged_skills.resolve().parent != bundle.resolve():
        raise SystemExit(f"refusing to replace skills outside bundle: {packaged_skills}")
    if packaged_skills.exists():
        shutil.rmtree(packaged_skills)
    for skill in spec["mcp"]["capabilityProfiles"][mode]["skills"]:
        source = repo / "skills" / skill
        if not source.is_dir():
            raise SystemExit(f"missing owned skill source: {source}")
        shutil.copytree(source, packaged_skills / skill)
    out = bundle / "cordis.patch.yml"
    out.write_text(patch, encoding="utf-8", newline="\n")
    (bundle / "runtime-policy.json").write_text(
        json.dumps(runtime_policy(spec, mode), indent=2) + "\n", encoding="utf-8")
    # The expected persona text is a build artifact for the validator, not part of
    # the bundle: a linked directory is never filtered by `files`.
    expected = bundle.parent / (bundle.name + ".persona.expected.txt")
    expected.write_text(block, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(patch)} chars, {patch.count(chr(10))} lines)")
    print(f"wrote {expected}")


if __name__ == "__main__":
    main()
