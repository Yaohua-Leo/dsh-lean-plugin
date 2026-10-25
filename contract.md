---
contract-version: 1
scope: always-on (injected into harness instruction files and the DSH persona prefix)
---

# Lean formalization contract

This block is injected verbatim into every supported harness by `install/`.
It is the always-on part of the setup: skills carry the procedure, this carries
the rules that must hold even in a workspace whose own instructions were not
loaded. `skills/lean-formalization/SKILL.md` carries the routing detail.

## Non-negotiables

- Never present a proof as complete while `sorry`, `admit`, a custom `axiom`, or
  error diagnostics remain in the delivered file. `sorry` is allowed only as a
  temporary placeholder inside a file you are actively editing.
- Never change a definition, hypothesis, quantifier, or conclusion to make a
  proof compile. If the statement looks false, attempt a counterexample and
  report the outcome.
- One tactic at a time: change one step, read diagnostics, repeat. Fix errors in
  order — syntax, then type errors, then unsolved goals and tactic failures, then
  linter warnings. Stop writing tactics after any error.
- At most three substantively different routes per target. On failure keep the
  target, its hypotheses, and the minimal blocker; report it as unresolved rather
  than silently narrowing the goal.
- Never leave `sorry`, `admit`, a custom `axiom`, or an error diagnostic in a
  delivered file. Neither a successful speculative probe nor a clean diagnostic
  list is acceptance.
- Report the real commands you ran and their exit codes. Anything you did not
  observe is `unknown`, never "passed". Do not invent build results, page
  numbers, citations, or review records.
- You are never the acceptance authority for mathematics. A target counts as
  verified only for the version actually delivered, after the project's
  deterministic build and axiom audit passed and an independent reviewer checked
  the statement against the source.
- Keep proving and acceptance separate: the agent that writes a proof never
  signs off on it.

## Inner loop and authority

- Inner loop: the live proof-state MCP tools (goal state, diagnostics,
  speculative probes) and the library-search MCP tools. The installed project
  configuration `lean-formalization.json` records which servers are mounted and
  in which mode (`beam` or `lsp-fallback`).
- Acceptance authority: the project's own deterministic build
  (`lake --no-cache build`), its axiom audit (`LeanAudit.lean`, whitelist below),
  its project gate (`leancheck`), and an independent reviewer's semantic
  comparison. Tool output never replaces them.

## Project-specific rules (injected)

The installer appends the project's own rules here, read from
`lean-formalization.json` (`allowedAxioms`, `projectRules`). Nothing in this
section weakens the non-negotiables above.

- Axiom whitelist: `propext`, `Classical.choice`, `Quot.sound`
  (`sorryAx` or any other axiom is a failure of the audit).
