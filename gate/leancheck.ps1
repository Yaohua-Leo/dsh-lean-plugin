<#
    leancheck.ps1 — the project gate.

    Reads lean-formalization.json from the project root and runs, in order:

      1.  lake --no-cache build <buildTargets...> <entryModules...>
      2.  lake env lean --run <leanAuditScript> <library> -- <targets...>
      3.  an axiom-whitelist check over every reported declaration
      4.  a locked-statement check: each target's printed type must equal the
          type recorded in <lockFile> (default locked-targets.json)

    It writes evidence under <evidenceDir>/runs/<UTC stamp>-<short id>/
    (report.md, report.json, command-*.log) and replaces LATEST.md with a
    navigation copy. Exit 0 only when every command exited 0, every configured
    target was reported, every axiom is in the whitelist, and every target still
    means what the lock says.

    Step 4 is the answer to "the proof compiles, but the statement changed". The
    first run has no lock: pass -Lock once the targets are the statements you
    actually want, review locked-targets.json, and commit it. Without a lock the
    gate FAILS closed; it never treats an unverified statement as verified.

    The script is project-agnostic: everything project-specific comes from
    lean-formalization.json. It never edits the project's sources.

    Usage:
      pwsh -File scripts/leancheck.ps1
      pwsh -File scripts/leancheck.ps1 -Lock             # (re)write the lock
      pwsh -File scripts/leancheck.ps1 -NoBuild          # audit only
      pwsh -File scripts/leancheck.ps1 -Config other.json
#>
[CmdletBinding()]
param(
    [string]$Config = 'lean-formalization.json',
    [switch]$NoBuild,
    [switch]$Lock
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Get-Location).Path
$configPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $projectRoot $Config }
if (!(Test-Path -LiteralPath $configPath -PathType Leaf)) {
    Write-Host "leancheck: config not found: $configPath" -ForegroundColor Red
    exit 2
}

$cfg = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$library = $cfg.library
if (-not $library) { Write-Host 'leancheck: config has no "library"' -ForegroundColor Red; exit 2 }

$targets      = @($cfg.targets)
$entryModules = @($cfg.entryModules)
$buildTargets = if ($cfg.buildTargets) { @($cfg.buildTargets) } else { @($library) }
$allowed      = @($cfg.allowedAxioms)
$evidenceRoot = if ($cfg.evidenceDir) { Join-Path $projectRoot $cfg.evidenceDir } else { Join-Path $projectRoot 'evidence/lean' }
$lake         = if ($cfg.lakeCommand) { $cfg.lakeCommand } else { 'lake' }
$auditScript  = if ($cfg.leanAuditScript) { $cfg.leanAuditScript } else { 'LeanAudit.lean' }
$scanScript   = if ($cfg.scanScript) { $cfg.scanScript } else { 'LeanScan.lean' }
# Module prefixes that belong to THIS library. Without them the scan cannot tell
# project declarations from Mathlib's, so it is skipped (and says so) rather than
# reporting an empty scan as clean.
$ownPrefixes  = @($cfg.ownModulePrefixes | Where-Object { $_ -and "$_".Trim() })
$minDupChars  = if ($cfg.minDuplicateTypeChars) { [int]$cfg.minDuplicateTypeChars } else { 40 }

if ($targets.Count -eq 0) {
    Write-Host 'leancheck: config lists no targets; refusing to report an empty audit as success' -ForegroundColor Red
    exit 2
}

# Some checkouts have `.lake/packages/*` owned by a different account than the one
# running the build; git then fails with "dubious ownership" and exits 128 before
# Lake builds anything. Grant safe.directory FOR THIS INVOCATION ONLY (never in the
# user's global git config). Configure the list in lean-formalization.json.
if ($cfg.gitSafeDirectories -and @($cfg.gitSafeDirectories).Count -gt 0) {
    $dirs = @($cfg.gitSafeDirectories)
    $env:GIT_CONFIG_COUNT = $dirs.Count.ToString()
    for ($i = 0; $i -lt $dirs.Count; $i++) {
        Set-Item -Path ("Env:GIT_CONFIG_KEY_{0}" -f $i) -Value 'safe.directory'
        Set-Item -Path ("Env:GIT_CONFIG_VALUE_{0}" -f $i) -Value ([string]$dirs[$i]).Replace('\', '/')
    }
}

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$shortId = -join ((1..6) | ForEach-Object { '0123456789abcdef'[(Get-Random -Maximum 16)] })
$runDir = Join-Path $evidenceRoot "runs/$stamp-$shortId"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$results = New-Object System.Collections.ArrayList
$lines   = New-Object System.Collections.ArrayList

function Invoke-Step {
    param([string]$Name, [string]$Exe, [string[]]$Arguments)
    Write-Host "==> $Name"
    $started = Get-Date
    $output = @()
    $code = 0
    # With $ErrorActionPreference = 'Stop', a command that cannot be resolved
    # raises a terminating CommandNotFoundException before anything is logged, and
    # the run directory would stay empty while LATEST.md kept the previous PASS.
    # A resolution failure is therefore recorded as a failed step (exit 127), and
    # the script always reaches the report.
    $resolved = $null
    if ([System.IO.File]::Exists($Exe)) {
        $resolved = $Exe
    } else {
        $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
        if ($cmd) { $resolved = $cmd.Source }
    }
    if (-not $resolved) {
        $code = 127
        $output = @(
            "leancheck: cannot resolve '$Exe'.",
            "Set lakeCommand (or lake) to an absolute path in lean-formalization.json, or repair PATH.",
            "Nothing was executed for this step."
        )
    } else {
        try {
            $output = & $resolved @Arguments 2>&1
            $code = $LASTEXITCODE
            if ($null -eq $code) { $code = 0 }
        } catch {
            $code = 127
            $output = @($_ | Out-String)
        }
    }
    $seconds = [int]((Get-Date) - $started).TotalSeconds
    $text = ($output | Out-String)
    Set-Content -LiteralPath (Join-Path $runDir "command-$Name.log") -Value $text -Encoding utf8
    [void]$lines.Add("### $Name (exit $code, ${seconds}s)")
    [void]$lines.Add(($text.TrimEnd()))
    [void]$lines.Add('')
    [void]$results.Add([pscustomobject]@{
        step = $Name; exitCode = $code; seconds = $seconds
        command = "$Exe $($Arguments -join ' ')"
        tail = (($output | Select-Object -Last 8) -join "`n")
    })
    Write-Host "    exit $code in ${seconds}s"
    return $code
}

Push-Location $projectRoot
$scanRan = $false
try {
    if (-not $NoBuild) {
        $buildArgs = @('--no-cache', 'build') + $buildTargets + $entryModules
        [void](Invoke-Step -Name 'build' -Exe $lake -Arguments $buildArgs)
    }
    [void](Invoke-Step -Name 'axiom-audit' -Exe $lake -Arguments (@('env', 'lean', '--run', $auditScript, $library, '--') + $targets))
    if ($ownPrefixes.Count -gt 0 -and (Test-Path -LiteralPath (Join-Path $projectRoot $scanScript) -PathType Leaf)) {
        $scanArgs = @('env', 'lean', '--run', $scanScript, $library, '--')
        foreach ($prefix in $ownPrefixes) { $scanArgs += @('--own', [string]$prefix) }
        $scanArgs += @('--min-type-chars', $minDupChars.ToString())
        [void](Invoke-Step -Name 'library-scan' -Exe $lake -Arguments $scanArgs)
        $scanRan = $true
    } else {
        if ($ownPrefixes.Count -eq 0) {
            Write-Host '    library-scan skipped: ownModulePrefixes is empty in the config'
        } else {
            Write-Host "    library-scan skipped: $scanScript is missing from the project"
        }
    }
} finally {
    Pop-Location
}

# ── whitelist check over the reported declarations ──────────────────────────
$reported = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $runDir 'command-axiom-audit.log') -ErrorAction SilentlyContinue) {
    $idx = $line.IndexOf('LEANCHECK_JSON:')
    if ($idx -lt 0) { continue }
    $decoded = $line.Substring($idx + 'LEANCHECK_JSON:'.Length) | ConvertFrom-Json
    $reported[$decoded.name] = $decoded
}

$failures = New-Object System.Collections.ArrayList
foreach ($target in $targets) {
    if (-not $reported.ContainsKey($target)) { [void]$failures.Add("target not reported: $target"); continue }
    $extra = @($reported[$target].axioms | Where-Object { $allowed -notcontains $_ })
    if ($extra.Count -gt 0) {
        [void]$failures.Add("$target depends on axioms outside the whitelist: $($extra -join ', ')")
    }
}

$stepFailures = @($results | Where-Object exitCode -ne 0)
$ok = ($stepFailures.Count -eq 0) -and ($failures.Count -eq 0)

# ── library scan: sorryAx reachability and duplicate statements ─────────────
$scanned = @()
$warnings = New-Object System.Collections.ArrayList
if ($scanRan) {
    $parsed = New-Object System.Collections.ArrayList
    foreach ($line in Get-Content -LiteralPath (Join-Path $runDir 'command-library-scan.log') -ErrorAction SilentlyContinue) {
        $idx = $line.IndexOf('LEANSCAN_JSON:')
        if ($idx -lt 0) { continue }
        [void]$parsed.Add(($line.Substring($idx + 'LEANSCAN_JSON:'.Length) | ConvertFrom-Json))
    }
    $scanned = @($parsed)

    # A definition or helper that still rests on `sorryAx` is a hollow proof: the
    # axiom audit only sees it when a target happens to use it, so report it here
    # for the whole library.
    $sorryNames = @($scanned | Where-Object { $_.sorryAx } | ForEach-Object { $_.name } | Sort-Object -Unique)
    foreach ($name in $sorryNames) {
        if ($targets -contains $name) { continue }  # already reported by the axiom whitelist
        $mod = ($scanned | Where-Object { $_.name -eq $name } | Select-Object -First 1).module
        [void]$failures.Add("declaration depends on sorryAx: $name ($mod)")
    }

    # A restated theorem is a fork of the library's own meaning. Two library
    # declarations with the same elaborated type and a non-trivial statement are
    # reported: a warning normally, a failure when a target is one of them.
    $groups = @($scanned |
        Where-Object { $_.kind -eq 'theorem' -and [int]$_.typeChars -ge $minDupChars } |
        Group-Object type |
        Where-Object { $_.Count -gt 1 })
    foreach ($g in $groups) {
        $names = @($g.Group.name | Sort-Object)
        $touchesTarget = @($names | Where-Object { $targets -contains $_ }).Count -gt 0
        if ($touchesTarget) {
            [void]$failures.Add("duplicate statement involves a target: $($names -join ', ')")
        } else {
            [void]$warnings.Add("duplicate statement: $($names -join ', ')")
        }
    }
}

# ── locked-statement check ──────────────────────────────────────────────────
$lockPath = if ($cfg.lockFile) { Join-Path $projectRoot $cfg.lockFile } else { Join-Path $projectRoot 'locked-targets.json' }
$lockState = 'absent'

function Get-TypeHash([string]$Text) {
    $normalized = ($Text -replace '\s+', ' ').Trim()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalized)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

if ($Lock) {
    # Locking is an act of the human reviewing the statements: this only records
    # what the environment reports now, and says so in the run.
    $entries = [ordered]@{}
    foreach ($target in $targets) {
        if (-not $reported.ContainsKey($target)) { continue }
        $entries[$target] = [ordered]@{
            kind = $reported[$target].kind
            module = $reported[$target].module
            typeHash = Get-TypeHash ([string]$reported[$target].type)
            type = [string]$reported[$target].type
        }
    }
    $lockDoc = [ordered]@{
        schemaVersion = 1
        note = 'Locked statements. Changing one is a change of the target, not a proof step: review it and re-lock deliberately.'
        library = $library
        lockedUtc = $stamp
        targets = $entries
    }
    $lockDoc | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $lockPath -Encoding utf8
    $lockState = "written ($($entries.Count) targets)"
    Write-Host "locked statements -> $lockPath"
} elseif (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    $lockState = 'missing'
    [void]$failures.Add("no statement lock at $lockPath; run leancheck -Lock once the targets are the statements you want, then commit the file")
} else {
    $lockDoc = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
    $lockedTargets = $lockDoc.targets
    $drift = 0
    foreach ($target in $targets) {
        if (-not $reported.ContainsKey($target)) { continue }
        $locked = $lockedTargets.$target
        if ($null -eq $locked) {
            [void]$failures.Add("target not in the lock: $target")
            $drift++
            continue
        }
        $now = Get-TypeHash ([string]$reported[$target].type)
        if ($now -ne $locked.typeHash) {
            [void]$failures.Add("locked statement changed: $target`n    locked: $($locked.type)`n    now:    $($reported[$target].type)")
            $drift++
        }
    }
    $lockState = if ($drift -eq 0) { "ok ($($targets.Count) targets)" } else { "DRIFT ($drift)" }
}

$ok = ($stepFailures.Count -eq 0) -and ($failures.Count -eq 0)

$report = [pscustomobject]@{
    gate = 'leancheck'; ok = $ok; timestampUtc = $stamp; runId = "$stamp-$shortId"
    projectRoot = $projectRoot; config = $configPath; library = $library
    targets = $targets; allowedAxioms = $allowed
    lockFile = $lockPath; lockState = $lockState; lockWritten = [bool]$Lock
    scanRan = $scanRan; scannedDeclarations = $scanned.Count
    sorryDependents = @($scanned | Where-Object { $_.sorryAx } | Sort-Object name |
        ForEach-Object { [pscustomobject]@{ name = $_.name; module = $_.module } })
    warnings = @($warnings)
    steps = $results; whitelistFailures = @($failures)
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $runDir 'report.json') -Encoding utf8

$md = New-Object System.Collections.ArrayList
[void]$md.Add("# leancheck report — $stamp-$shortId")
[void]$md.Add('')
[void]$md.Add("- project: ``$projectRoot``")
[void]$md.Add("- library: ``$library``")
[void]$md.Add("- targets: $($targets.Count)")
[void]$md.Add("- allowed axioms: ``$($allowed -join ', ')``")
[void]$md.Add("- statement lock: $lockState")
[void]$md.Add("- library scan: $(if ($scanRan) { "$($scanned.Count) declarations" } else { 'skipped (ownModulePrefixes empty or scan script missing)' })")
[void]$md.Add("- result: **$(if ($ok) { 'PASS' } else { 'FAIL' })**
")
[void]$md.Add('## steps')
[void]$md.Add('')
[void]$md.Add('| step | exit | seconds |')
[void]$md.Add('|---|---|---|')
foreach ($r in $results) { [void]$md.Add("| $($r.step) | $($r.exitCode) | $($r.seconds) |") }
[void]$md.Add('')
if ($failures.Count -gt 0) {
    [void]$md.Add('## failures')
    [void]$md.Add('')
    $failures | ForEach-Object { [void]$md.Add("- $_") }
    [void]$md.Add('')
}
if ($warnings.Count -gt 0) {
    [void]$md.Add('## warnings')
    [void]$md.Add('')
    $warnings | ForEach-Object { [void]$md.Add("- $_") }
    [void]$md.Add('')
}
[void]$md.Add('## axioms per target')
[void]$md.Add('')
[void]$md.Add('| target | kind | axioms |')
[void]$md.Add('|---|---|---|')
foreach ($target in $targets) {
    if ($reported.ContainsKey($target)) {
        $ax = @($reported[$target].axioms) -join ', '
        [void]$md.Add("| $target | $($reported[$target].kind) | $($ax -replace '\|', '\|') |")
    } else {
        [void]$md.Add("| $target | (missing) | |")
    }
}
Set-Content -LiteralPath (Join-Path $runDir 'report.md') -Value $md -Encoding utf8

# LATEST.md is a navigation copy, never a replacement for the run history.
$latest = New-Object System.Collections.ArrayList
[void]$latest.Add('# leancheck — latest run')
[void]$latest.Add('')
[void]$latest.Add("Latest run: ``$stamp-$shortId`` -> ``$($cfg.evidenceDir)/runs/$stamp-$shortId/report.md``")
[void]$latest.Add('')
[void]$latest.Add("Result: $(if ($ok) { 'PASS' } else { 'FAIL' })")
[void]$latest.Add('')
[void]$latest.Add('History is appended, never erased: every run keeps its own directory.')
Set-Content -LiteralPath (Join-Path $evidenceRoot 'LATEST.md') -Value $latest -Encoding utf8

Write-Host ''
$results | Format-Table step, exitCode, seconds -AutoSize
Write-Host "evidence: $runDir"
if ($warnings.Count -gt 0) {
    Write-Host "warnings ($($warnings.Count)):" -ForegroundColor Yellow
    $warnings | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
}
if (-not $ok) {
    if ($stepFailures.Count -gt 0) { Write-Host "FAILED steps: $($stepFailures.step -join ', ')" -ForegroundColor Red }
    $failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    exit 1
}
Write-Host 'leancheck: PASS'
exit 0
