# CLAUDE.md

Claude Code reads `AGENTS.md` in this repository as the authoritative project
instruction file. Follow it.

If the user asked you to *become* the Lean formalization assistant on this
machine, read `BOOTSTRAP.md` and follow it step by step; it is the complete
procedure, and it says which surfaces you may write to and how to verify the
result.

Install-side notes specific to Claude Code:

- the contract block is appended to `~/.claude/CLAUDE.md` (user scope) and/or
  `CLAUDE.md` (project scope), between the `<!-- lean-formalization:begin v1 -->`
  and `<!-- lean-formalization:end -->` markers;
- the skills are copied to `~/.claude/skills` and/or `.claude/skills`;
- the Lean LSP server is written to `.mcp.json` (project scope). For user scope the
  installer documents `claude mcp add --scope user ...` instead of editing
  `~/.claude.json`, which the CLI owns;
- the nine upstream `leanprover/skills` skills come from
  `claude plugin marketplace add https://github.com/leanprover/skills.git` followed
  by `claude plugin install lean@leanprover`.
