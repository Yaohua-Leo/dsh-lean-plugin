<#
.SYNOPSIS
Stage a mode for a NEW DSH session; Beam requires an actual project sync.
.EXAMPLE
pwsh -File .\tools\set-mode.ps1 -Fallback -Project E:\my-project
.EXAMPLE
pwsh -File .\tools\set-mode.ps1 -Beam -Project E:\my-project -ProbeFile MyLib\Basic.lean -BeamCommand C:\Lean\bin\lean-beam-mcp.exe
#>
[CmdletBinding(DefaultParameterSetName = 'Fallback')]
param(
    [Parameter(ParameterSetName = 'Fallback')][switch]$Fallback,
    [Parameter(ParameterSetName = 'Beam')][switch]$Beam,
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$ProbeFile = '',
    [string]$BeamCommand = '',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$mode = if ($Beam) { 'beam' } else { 'lsp-fallback' }
$params = @((Join-Path $PSScriptRoot 'set_lean_mode.py'), '--root', $Root, '--mode', $mode, '--project', $Project)
if ($Beam) {
    if (-not $BeamCommand) {
        . (Join-Path $PSScriptRoot 'beam-detect.ps1')
        $launcher = Get-BeamLauncher
        if (-not $launcher.Found) { throw 'No Beam launcher. See docs/dsh-kit.md for the pinned runtime setup.' }
        $BeamCommand = $launcher.Command
    }
    $params += @('--beam-command', $BeamCommand, '--probe-file', $ProbeFile)
}
if ($DryRun) { $params += '--dry-run' }
& python @params
$code = $LASTEXITCODE
if ($code -eq 0 -and -not $DryRun) {
    Write-Host 'Close the old Lean session. Reload the bundle in DSH Desktop and start a NEW session; call lean_selfcheck first.'
}
exit $code
