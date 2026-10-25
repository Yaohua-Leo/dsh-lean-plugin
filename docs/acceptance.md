# Acceptance boundaries

The original 1.1.0 preset was exercised in native DSH Desktop 0.2.1-rc.2 on a
real Lean 4.35.0 theorem. `lean_selfcheck` reported matching `lsp-fallback` modes,
16 LSP tools, zero Beam tools, and no required/forbidden-tool violations.
The skill loader used the installed preset's own isolated skill directory.
An initial relative file path failed; the absolute-path retry, goal query,
diagnostics and advisory axiom check succeeded. No source edits or shell calls
were performed by that Desktop acceptance session.

This public repository adds a root DSH package entry and resolves skills beside
the loaded runtime module, supporting both root and nested local installation.
Public-package validation is recorded in [validation](dsh-kit-validation.md).
The original private session receipts and machine paths are not distributed.

Beam runtime acceptance is **not run**. Mock controller tests are not Beam
execution evidence. A successful sync establishes project compatibility only.
The final project build, axiom audit, statement lock, library scan and independent
semantic review remain the proof acceptance authority.
