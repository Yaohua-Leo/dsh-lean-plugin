<#
    leanstatus.ps1 — what is left, without rebuilding anything.

    Reads lean-formalization.json, the statement lock and the newest leancheck run
    under <evidenceDir>/runs/, then reports the state a human or an agent needs:
    whether the last gate run passed, which targets are locked, and which library
    declarations still rest on `sorryAx`.

    Why this exists: a `sorry` count is not progress — splitting a proof raises it
    while work advances, and a file with no `sorry` can still rest on a wrong
    definition. This reports the gate's own facts instead of a guess.

    With -WriteState it rewrites <project>/coord/STATE.md (current state, never
    appended) when the project has a coord/ directory. That file is the SHEAF-style
    hand-off point for a human or the next session; leanstatus only writes the
    machine-derived part and keeps any existing `## Plan` section.

    Usage:
      pwsh -File scripts/leanstatus.ps1
      pwsh -File scripts/leanstatus.ps1 -WriteState
#>
[CmdletBinding()]
param(
    [string]$Config = 'lean-formalization.json',
    [switch]$WriteState
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Get-Location).Path
$configPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $projectRoot $Config }
if (!(Test-Path -LiteralPath $configPath -PathType Leaf)) {
    Write-Host "leanstatus: config not found: $configPath" -ForegroundColor Red
    exit 2
}
$cfg = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$targets = @($cfg.targets)
$evidenceRoot = if ($cfg.evidenceDir) { Join-Path $projectRoot $cfg.evidenceDir } else { Join-Path $projectRoot 'evidence/lean' }
$lockPath = if ($cfg.lockFile) { Join-Path $projectRoot $cfg.lockFile } else { Join-Path $projectRoot 'locked-targets.json' }

$run = Get-ChildItem -LiteralPath (Join-Path $evidenceRoot 'runs') -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
$report = $null
if ($run) {
    $reportFile = Join-Path $run.FullName 'report.json'
    if (Test-Path -LiteralPath $reportFile) { $report = Get-Content -LiteralPath $reportFile -Raw | ConvertFrom-Json }
}

$locked = $null
if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
    $locked = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
}

$remaining = @()
if ($report -and $report.sorryDependents) { $remaining = @($report.sorryDependents) }
$warnings = @()
if ($report -and $report.warnings) { $warnings = @($report.warnings) }

Write-Host "lean status — $projectRoot"
Write-Host ("  mode      : {0}" -f $(if ($cfg.mode) { $cfg.mode } else { '(unset)' }))
Write-Host ("  targets   : {0} configured, {1} locked" -f $targets.Count, $(if ($locked) { @($locked.targets.PSObject.Properties).Count } else { 0 }))
if ($report) {
    Write-Host ("  last run  : {0}  {1}" -f $report.runId, $(if ($report.ok) { 'PASS' } else { 'FAIL' }))
    $steps = @($report.steps | ForEach-Object { "$($_.step)=$($_.exitCode)" })
    Write-Host ("  steps     : {0}" -f ($steps -join ', '))
    Write-Host ("  scan      : {0}" -f $(if ($report.scanRan) { "$($report.scannedDeclarations) declarations" } else { 'not run (ownModulePrefixes empty?)' }))
} else {
    Write-Host '  last run  : none yet — run scripts/leancheck.ps1'
}
Write-Host ("  remaining : {0} declaration(s) depend on sorryAx" -f $remaining.Count)
foreach ($r in $remaining) { Write-Host ("    - {0}  [{1}]" -f $r.name, $r.module) }
if ($warnings.Count -gt 0) {
    Write-Host ("  warnings  : {0}" -f $warnings.Count)
    $warnings | ForEach-Object { Write-Host "    - $_" }
}

if ($WriteState) {
    $coord = Join-Path $projectRoot 'coord'
    if (-not (Test-Path -LiteralPath $coord -PathType Container)) {
        Write-Host "leanstatus: no coord/ directory, STATE.md not written" -ForegroundColor Yellow
        exit 1
    }
    $statePath = Join-Path $coord 'STATE.md'
    $plan = ''
    if (Test-Path -LiteralPath $statePath) {
        $old = Get-Content -LiteralPath $statePath -Raw
        $idx = $old.IndexOf('## Plan')
        if ($idx -ge 0) { $plan = $old.Substring($idx) }
    }
    $md = New-Object System.Collections.ArrayList
    [void]$md.Add('# STATE')
    [void]$md.Add('')
    [void]$md.Add("Updated: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')) by leanstatus.ps1 (rewritten, never appended).")
    [void]$md.Add('')
    [void]$md.Add('## Stages open')
    if ($report) {
        [void]$md.Add(("- gate: **{0}** at ``{1}``" -f $(if ($report.ok) { 'PASS' } else { 'FAIL' }), $report.runId))
    } else {
        [void]$md.Add('- gate: no run yet')
    }
    [void]$md.Add(("- statement lock: {0}" -f $(if ($locked) { "$(@($locked.targets.PSObject.Properties).Count)/$($targets.Count) targets locked" } else { 'absent' })))
    [void]$md.Add(("- remaining: {0} declaration(s) depend on sorryAx" -f $remaining.Count))
    [void]$md.Add('')
    [void]$md.Add('## Targets')
    [void]$md.Add('')
    [void]$md.Add('| target | locked type |')
    [void]$md.Add('|---|---|')
    foreach ($t in $targets) {
        $lt = ''
        if ($locked) {
            $entry = $locked.targets.$t
            if ($entry) { $lt = ([string]$entry.type).Replace('|', '\|') } else { $lt = '(not in lock)' }
        }
        [void]$md.Add("| $t | $lt |")
    }
    [void]$md.Add('')
    [void]$md.Add('## Remaining work')
    [void]$md.Add('')
    if ($remaining.Count -eq 0) {
        [void]$md.Add('- nothing: no library declaration depends on sorryAx')
    } else {
        foreach ($r in $remaining) { [void]$md.Add(("- ``{0}`` [{1}] — proof rests on sorryAx" -f $r.name, $r.module)) }
    }
    [void]$md.Add('')
    if (-not $plan) { $plan = "## Plan`n`n- (human or agent: the next steps, each one checkable)`n" }
    Set-Content -LiteralPath $statePath -Value (($md -join "`n") + "`n" + $plan) -Encoding utf8
    Write-Host "wrote $statePath"
}

exit 0
