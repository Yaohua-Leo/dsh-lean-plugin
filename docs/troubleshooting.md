# Troubleshooting

- Missing Lean tools: inspect `lean_selfcheck`; verify uvx, ripgrep and the pinned
  LSP package. Mounted servers fail closed on startup errors.
- Mode mismatch: use `tools/set-mode.ps1` with the exact project and restart into
  a new session. Never silently switch backends inside an existing proof session.
- Invalid LSP file path: pass an absolute `file_path`. DSH's MCP process may run
  from a different directory than the active project.
- Local search in Beam mode: pass `project_root` explicitly.
- Beam not available: this package contains the skill, policy and probe, not
  native Beam binaries. Use a runtime built from the pinned source revision and
  probe the actual project's `.lean` file before activating.
- No gate or empty targets: scaffold the project, review library/targets and
  statements, then run leancheck. A readable lock or tool catalog is not a proof.
- A long initial sync: use the standalone `probe_beam_project.py --timeout`
  option to diagnose initialization. Never promote a timed-out probe to success.

The plugin and Lean runtime are separate. Installation succeeds independently
of whether a particular project builds or its mathematical statement is true.
