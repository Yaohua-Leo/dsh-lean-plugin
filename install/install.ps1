<#
    Launcher for the Lean formalization installer.

    All logic lives in install.py so the PowerShell and POSIX entry points cannot
    drift apart. This script only locates a Python 3 interpreter and forwards every
    argument, plus the exit code.

    Examples:
      pwsh -File install/install.ps1 --dry-run
      pwsh -File install/install.ps1 --project C:\path\to\lean --scope both
      pwsh -File install/install.ps1 --uninstall
      pwsh -File install/install.ps1 --doctor
#>
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'install.py'
if (!(Test-Path -LiteralPath $script)) { throw "missing $script" }

$candidates = @('python', 'python3', 'py')
$python = $null
foreach ($candidate in $candidates) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}
if (-not $python) {
    Write-Error "no python interpreter found on PATH (tried: $($candidates -join ', '))"
    exit 2
}

$forwarded = @()
if ($Rest) { $forwarded = $Rest }
& $python $script @forwarded
exit $LASTEXITCODE
