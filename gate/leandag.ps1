<#
    leandag.ps1 — thin launcher for leandag.py (the statement DAG and its queue).

    All logic lives in ../leandag.py so this wrapper and leandag.sh cannot drift.
    Reads coord/nodes.jsonl, derives reachability from the targets, the pruning
    candidates, readiness and the distance ordering, cross-checks the newest gate
    report, and writes coord/queue.tsv + coord/queue.md.

    Exit 1 means the DAG is structurally broken (cycle, unknown dependency,
    duplicate id, no target); exit 2 means there is no node file yet.

    Usage:
      pwsh -File scripts/leandag.ps1
      pwsh -File scripts/leandag.ps1 -State      # also rewrite coord/DAG.md
      pwsh -File scripts/leandag.ps1 -Nodes coord/other.jsonl
#>
[CmdletBinding()]
param(
    [string]$Project = (Get-Location).Path,
    [string]$Nodes,
    [switch]$State,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$core = Join-Path (Split-Path $PSScriptRoot -Parent) 'leandag.py'
if (-not (Test-Path -LiteralPath $core)) { throw "leandag core not found: $core" }

$python = $null
foreach ($candidate in 'python3', 'python') {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}
if (-not $python) { Write-Host 'leandag: python3 (or python) is required' -ForegroundColor Red; exit 2 }

$args = @($core, '--project', $Project)
if ($Nodes) { $args += @('--nodes', $Nodes) }
if ($State) { $args += '--state' }
if ($Json) { $args += '--json' }
& $python @args
exit $LASTEXITCODE
