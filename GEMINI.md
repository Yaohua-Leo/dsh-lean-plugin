# GEMINI.md

Gemini CLI reads `AGENTS.md` in this repository as the authoritative project
instruction file. Follow it.

If the user asked you to *become* the Lean formalization assistant on this
machine, read `BOOTSTRAP.md` and follow it step by step.

Install-side notes specific to Gemini CLI:

- the contract block is appended to `~/.gemini/GEMINI.md` (user scope) and/or
  `GEMINI.md` (project scope), between the `<!-- lean-formalization:begin v1 -->`
  and `<!-- lean-formalization:end -->` markers;
- the skills are copied to `~/.gemini/skills`;
- the Lean LSP server is written into the `mcpServers` object of
  `~/.gemini/settings.json`. The `gemini mcp` subcommand was observed to hang in a
  non-interactive shell on the authoring machine, which is why the file is written
  directly and then verified by `python verify/probe_mcp.py --harnesses`;
- the nine upstream `leanprover/skills` skills come from
  `gemini skills install https://github.com/leanprover/skills --path skills`.
