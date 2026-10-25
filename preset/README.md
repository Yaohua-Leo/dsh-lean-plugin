# Lean证明助手 — DSH bundle 1.1.0

Package: `@local/dsh-lean-preset`; preset: `lean` / 「Lean证明助手」.
Install this directory as a local DSH bundle. The portable ZIP includes the
canonical sources, mode switcher, project probes and gate scaffolding.
See [the Chinese quickstart](../docs/dsh-kit.md) for installation and switching.

## Two explicit modes

| Capability | lsp-fallback (default) | beam |
|---|---|---|
| Proof state, diagnostics and navigation | lean-lsp | Lean Beam |
| Speculative tactic checks | lean_multi_attempt | lean_run_at / handles |
| Library search and advisory analysis | lean-lsp | lean-lsp |
| Final acceptance | project gate and independent review | project gate and independent review |
| Skills | lean-formalization | lean-formalization + lean-beam |

`harnesses.json` owns the mode policy. The generator copies its selected mode
into `runtime-policy.json`, the MCP patch and the isolated skill directory.
`lean_selfcheck` checks required/forbidden tools and requires the project mode
to match the bundle. The skill registry, filesystem provider and loader share
one private realm, excluding inherited user/project skills.

LSP is pinned to `lean-lsp-mcp==0.31.0`; the Beam skill and accepted runtime
source commit are pinned together in `runtime-policy.json`. No Beam runtime
binary is included. Every mounted MCP server uses `failOnStartupError: true`.

## Switching and verification

Use the kit's `tools/set-mode.ps1` with an explicit `-Project`. Beam also needs
`-ProbeFile` and a compatible `-BeamCommand`. It performs a bounded MCP identity
and real project sync probe before staging any changes. The switch validates a
candidate, backs up the original bundle/config and rolls back on write failure.
It never treats executable detection or a tool list as successful project sync.

Restart DSH Desktop and open a NEW session after changing the bundle. Call
`lean_selfcheck` first. On failure, report the missing capability and stop;
choose fallback explicitly for a new session. An existing session never silently
changes backend. Desktop profiles are managed in Desktop, not CLI dump-config.

`mcpReady` describes the catalog and mode match. `gateStatus=ready` describes
readable gate configuration/lock only. Neither certifies a proof, a successful
Beam sync or independent review. Run the project's deterministic leancheck.

LSP local search in Beam mode must receive the explicit `project_root`.
Before the final build, drop the Beam workspace and wait for cleanup.
Keep file edits, Beam document versions and proof handles synchronized.

## Source layout

- `index.js`, `capabilities.js`: selfcheck implementation; only built-in/local imports.
- `runtime-policy.json`, `cordis.patch.yml`, `skills/`: generated mode assets.
- `package.json`, `locale/`, `icon.svg`: DSH identity and presentation.

Rebuild via `python tools/build_lean_preset.py . preset` at the kit root.
This low-level generator produces configuration only; use the guarded switcher
for actual Beam activation. Historical Desktop acceptance and current package
validation are recorded separately in `docs/acceptance.md` and
`docs/dsh-kit-validation.md` in the full kit.
