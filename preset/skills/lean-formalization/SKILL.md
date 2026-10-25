---
name: lean-formalization
description: Use when formalizing mathematics in Lean 4 — routes work between the live proof-state MCP tools (Lean Beam when it is installed, otherwise the Lean LSP server's own goal/diagnostic tools), the library-search MCP tools, and the deterministic build/axiom gate; defines the evidence and acceptance rules. Load it before touching a Lean target.
---

# Lean Formalization Workflow

Four layers exist. They are not alternatives; each owns a different question.

| Layer | Question it answers | Where |
|---|---|---|
| Method | How to write a Lean proof correctly | the `lean-proof`, `lean-setup`, `mathlib-build`, `lean-bisect`, `lean-mwe`, `lean-pr`, `mathlib-pr`, `mathlib-review`, `nightly-testing` skills |
| Live proof state | What is the goal here, what compiles, what is still `sorry` | Live proof-state MCP tools (see "Which mode you are in") |
| Library search | Which existing theorem matches this | Library-search MCP tools (`lean_local_search`, `lean_loogle`, `lean_leansearch`, `lean_leanfinder`, `lean_hammer_premise`) |
| Acceptance | Is this target actually verified at this version | The project's `lake build`, its `LeanAudit.lean` axiom audit, its `leancheck` gate, an independent reviewer |

The always-on rules (never leave `sorry`/custom `axiom`, never change a
statement to make it compile, one tactic at a time, three routes maximum, report
real commands and exit codes, never self-accept) live in the harness's injected
instruction block and in `contract.md`. This skill adds the routing detail.

## Which mode you are in

Read the project's `lean-formalization.json` (written by the installer):

```json
{
  "schemaVersion": 1,
  "mode": "beam",              // or "lsp-fallback"
  "allowedAxioms": ["propext", "Classical.choice", "Quot.sound"],
  "library": "<lake library name>",
  "targets": ["<Fully.Qualified.Name>", "..."],
  "entryModules": ["<Module.That.Imports.Everything>"],
  "evidenceDir": "evidence/lean",
  "checkCommand": "scripts/leancheck.ps1"
}
```

- `mode: beam` — Lean Beam is installed: Beam owns goal state, diagnostics,
  hover/definition/references/symbols, and speculative probes. The lean-lsp
  server is mounted with those tools disabled so there is exactly one owner.
- `mode: lsp-fallback` — Beam is not installed: lean-lsp keeps `lean_goal`,
  `lean_diagnostic_messages`, `lean_hover_info`, `lean_file_outline`,
  plus all search tools.
- In **both** modes `lean_build` and `lean_run_code` are disabled on purpose:
  builds must run as the deterministic `lake build` the project gate verifies,
  and `lean_run_code` is an arbitrary-code-execution surface.
- If the file is missing, do not guess the mode: run the installer's `doctor`
  or ask the user, then proceed.
- In DSH call `lean_selfcheck` before Lean work. The project mode and installed
  preset mode must agree. A missing backend blocks the session; select another
  mode explicitly and start a new session. Never silently fall back mid-proof.

## Mode A — Lean Beam (inner loop)

- Call `lean_sync` (or `lean_update`) first, keep the returned `version`, and
  pass it to the next snapshot-bound call for the same workspace and path.
- Every call carries an explicit workspace descriptor; there is no default
  workspace. Positions are 0-based and columns count UTF-16 units. Whitespace
  after a proof may still select a tactic context — pick a deliberate position,
  and use a command position for a top-level `#check`.
- `lean_run_at` is speculative: it evaluates text in the real module context
  **without changing the file**. To keep a result, edit and save the file with
  your own edit tools, then `lean_update` before the next snapshot-bound call.
  Never use `lean_sync` as a way to commit a probe.
- `lean_todo` is the inventory of sorries, holes, diagnostics and code actions
  for a file; `lean_goals` gives goal state at a position;
  `lean_hover`/`lean_definition`/`lean_references`/`lean_workspace_symbols`
  answer the rest.
- `lean_save` / `lean_close_save` write development checkpoints (build
  artifacts, never source). Do not turn them into a per-step ritual, and do not
  replace the final clean build with them.
- After a change to Lake configuration, dependencies or plugins, the running
  Lean server may keep stale configuration: call `lean_drop_workspace` (or
  restart the MCP row) before the next call that uses the Lean server.
- The MCP server owns its session. Do not start a separate CLI `serve` owner.
  Drop the workspace and wait for cleanup before the final project build.
- In this mode LSP provides search and advisory audit only. Do not call its
  `lean_multi_attempt`, goal, diagnostics or navigation tools as a second state owner.

## Mode B — lean-lsp only (inner loop)

- Pass an absolute `file_path` to LSP file tools; the DSH server process may
  have a different working directory from the current project.
- `lean_goal` (before/after at a position), `lean_diagnostic_messages`,
  `lean_hover_info`, `lean_file_outline`.
- `lean_multi_attempt` screens several tactics at one position without editing
  the file — this is the closest equivalent of a Beam `run_at` probe.
- File-based tools only operate inside the active Lean project, its resolved
  `.lake/packages/*` dependencies, and the Lean stdlib source tree.
- Reload discipline: the server re-reads the file from disk. Save edits before
  asking for diagnostics, and prefer a deliberate position over "somewhere in
  the proof".

### Beam ↔ LSP equivalents

| Intent | Beam (`mode: beam`) | lean-lsp (`mode: lsp-fallback`) |
|---|---|---|
| goal state at a position | `lean_goals` | `lean_goal` |
| diagnostics / readiness | `lean_sync`, `lean_todo` | `lean_diagnostic_messages` |
| speculative snippet without editing | `lean_run_at` (+ handles) | `lean_multi_attempt` (tactic screening) |
| navigation | `lean_hover`, `lean_definition`, `lean_references`, `lean_workspace_symbols` | `lean_hover_info`, `lean_references`, `lean_file_outline` |
| development checkpoint | `lean_save`, `lean_close_save` | none — use the project build |
| sorry/hole inventory | `lean_todo` | `lean_diagnostic_messages` + a text search |

## Search and screening (both modes)

- `lean_local_search` first (local project and stdlib) — it confirms a
  declaration exists instead of hallucinating an API. It needs `ripgrep` (`rg`)
  on PATH; if `rg` is missing, this tool is unavailable — report that instead of
  guessing names.
- In Beam mode pass the explicit absolute `project_root` to LSP's
  `lean_local_search`. Beam and LSP do not share an implicit current project.
- Then the remote tools: `lean_loogle`, `lean_leansearch`, `lean_leanfinder`,
  `lean_hammer_premise`. They are rate limited to roughly
  3 requests per 30 s; do not burn them on vague queries.
- `lean_minimal_hypotheses` reports which hypotheses are load-bearing (useful
  before sharpening a statement); `lean_profile_proof` explains a slow proof.
- `lean_verify` reports the axioms a declaration depends on plus `unsafe`/
  `set_option debug.*` style source patterns. Use it as a pre-check only — it
  does not replace the project's audit.

## Non-negotiable proof discipline

- One tactic at a time: change one step, read diagnostics, repeat.
- Fix errors in priority order — syntax, then type errors, then unsolved goals
  and tactic failures, then linter warnings. "unsolved goals" points at the
  `by`/`=>` line, not at the tactic you added. Stop writing tactics after any
  error.
- Never change a definition, hypothesis, quantifier or conclusion to make a
  proof compile; if the statement looks false, attempt a counterexample.
- Never leave `sorry`, `admit`, a custom `axiom`, or an error diagnostic in a
  delivered file. `sorry` is only a working placeholder inside a file you are
  actively editing.
- At most three substantively different routes per target. On failure keep the
  target, its hypotheses and the minimal blocker, and report it as unresolved
  instead of narrowing it silently.
- Never declare a proof complete while any of the above remains. Neither a
  successful speculative probe nor a clean diagnostic list is acceptance.

## Acceptance pipeline (the only authority)

1. Edit and save the source. Formal sources live only in the formal library
   directory; one entry module imports every formal module.
2. Build exactly what the gate builds — the library and every formal module,
   without the cache shortcut:
   `lake --no-cache build <defaultTargets...> <each entry module>`
   Run long builds as a background job; a background exit code is not a result
   until you read it.
3. Axiom audit — every target, plus the library's transitive declarations:
   `lake env lean --run LeanAudit.lean <lib> -- <target declaration names...>`
   The allowed axioms are the ones in `lean-formalization.json`
   (`propext`, `Classical.choice`, `Quot.sound` by default). `sorryAx` or any
   other axiom is a failure.
4. Project gate: the `checkCommand` from `lean-formalization.json`
   (e.g. `scripts/leancheck.ps1`, or `leancheck.cmd --no-pause`), then read the
   report it writes. Exit code 0 at the version you are delivering is required.
5. Independent semantic comparison: someone who did not write the proof
   re-checks the statement, hypotheses, quantifiers, normalization and range
   against the source text and the actual Lean type, bound to the exact versions
   delivered.

MCP output, a compiling file, a green checkpoint, or an empty problem list never
substitute for steps 2–5.

## Evidence

- Runs live under `<evidenceDir>/runs/<UTC timestamp>-<short id>/` with
  `report.md`, `report.json` and the raw `command-*.log` files; the "latest"
  report is a navigation copy, not a replacement for history.
- Record real commands, real exit codes, the toolchain and dependency commits,
  source SHA256, the Lean declaration kind, its full type, and the transitive
  axioms. Unknown values are written `unknown`.
- Changing a definition, a file, a lock file or a target makes the old semantic
  comparison stale. Re-run the affected checks; regenerating a file manifest
  does not restore a stale review, and mechanically rotating hashes does not
  replace a re-read.
- Failed and corrected records are appended, never erased.

## Environment notes

- `.lake/packages/*` may be owned by a different OS account than the one running
  the build, in which case git fails with "dubious ownership" and exits 128
  before Lake builds anything. Grant `safe.directory` **for that one invocation**
  (`GIT_CONFIG_COUNT` plus `GIT_CONFIG_KEY_<i>` / `GIT_CONFIG_VALUE_<i>`) and
  never rewrite ownership of the dependency checkouts or edit the global git
  config.
- `uvx` needs a writable cache and tool directory; in a restricted sandbox set
  `UV_CACHE_DIR` / `UV_TOOL_DIR` to writable paths in the MCP server's env.
- If Beam's toolchain pin and the project's `lean-toolchain` disagree, stop and
  report it — reconfigure or reinstall Beam; do not edit the wrapper.
- Keep proving and acceptance separate: the agent that writes a proof never
  signs off on it.
