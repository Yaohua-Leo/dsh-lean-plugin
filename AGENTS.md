# AGENTS.md — working inside the lean-formalization repository

This repository packages the Lean 4 formalization assistant: the always-on
contract, the routing skill, the per-harness adapters, the MCP server
configuration, and the acceptance gate scaffold. It is not a Lean project and it
does not prove anything itself.

## If the user asked you to *become* the assistant

Read `BOOTSTRAP.md` and follow it. That file is the complete procedure, including
the fetch ladder, the detection rules, what may be written, and how to verify.

## If you are changing this repository

- `harnesses.json` is the single source of truth for harness surfaces: detection,
  paths, scopes, the MCP method, the mode-dependent disabled-tool lists, and the
  TOML `fields` templates. Entry *shapes* for the JSON harnesses are still rendered
  by `install/install.py` (`json_shape`), because they carry per-harness structure
  (`.mcp.json` vs `servers` vs Vibe's array of tables). `verify/validate_repo.mjs`
  enforces the parts that can be checked mechanically: every provenance ledger row,
  and the presence of a template (`entry`/`shapeByMajor`/`fields`) for every
  harness whose method needs one. It does not cross-check prose paths in `docs/` —
  keep those in sync by hand.
- `contract.md` is the single source of truth for the always-on rules. The DSH
  persona prefix, the injected instruction block and the docs are all derived from
  it; if you change a rule, change it there and re-run the validators.
- Vendored upstream content is recorded in `skills/PROVENANCE.md` with hashes.
  Never edit a vendored file in place: update the pin, re-copy, re-hash.
- `gate/LeanAudit.lean` and `gate/leancheck.*` must stay project-agnostic:
  everything project-specific is read from `lean-formalization.json`.

## Checks that must pass before you call a change done

```bash
node verify/validate_repo.mjs        # structure, schema, frontmatter, vendored hashes
python verify/smoke.py --with-gate   # install → assert → idempotent → uninstall, plus a real Lean build
python install/install.py --doctor
```

Report the real commands and their real exit codes. Do not describe a check as
passing if you did not run it.

## The non-negotiables you work under

The full text is in `contract.md`; the short version, which applies to every Lean
target you touch while working here: never present a proof as complete while
`sorry`, `admit`, a custom `axiom` or an error diagnostic remains; never change a
definition, hypothesis, quantifier or conclusion to make a proof compile; one
tactic at a time with errors fixed in priority order; at most three substantively
different routes per target; report real commands and exit codes, with `unknown`
for anything you did not observe; and never sign off on your own mathematics.
