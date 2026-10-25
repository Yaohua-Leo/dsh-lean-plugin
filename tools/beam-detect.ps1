<#
.SYNOPSIS
  Find a real lean-beam-mcp launcher, in any of the shapes Beam supports.

.DESCRIPTION
  Dot-source this file, then call Get-BeamLauncher. Beam reaches a machine in three
  shapes, and the preset must name the right one:

    1. checkout install     -> `lean-beam-mcp` on PATH  (scripts/install-beam.sh,
                               documented for Linux/macOS only)
    2. user local bin       -> %USERPROFILE%\.local\bin\lean-beam-mcp.exe
    3. bundled with Lean    -> <toolchain>\bin\lean-beam-mcp.exe, launched by
                               absolute path (docs/TOOLCHAIN_BUNDLING.md); the
                               launcher is NOT usually on PATH

  A bundled server serves only projects whose `lean-toolchain` resolves to its
  containing installation, so the detected toolchain name is reported and must
  match the project being worked on.

  Verified 2026-10-20: the official leanprover/lean4 v4.36.0-rc1 Windows tarball
  contains no Beam entries, so shape 3 requires a distribution a builder opted
  into; an ordinary elan toolchain does not contain it.
#>

function Get-BeamLauncher {
    [CmdletBinding()]
    param(
        [string]$ElanHome = (Join-Path $env:USERPROFILE '.elan')
    )

    $candidates = New-Object System.Collections.ArrayList

    $onPath = Get-Command 'lean-beam-mcp' -ErrorAction SilentlyContinue
    if ($onPath) {
        [void]$candidates.Add([pscustomobject]@{ kind = 'path'; command = 'lean-beam-mcp'; detail = $onPath.Source })
    }

    $userBin = Join-Path $env:USERPROFILE '.local\bin\lean-beam-mcp.exe'
    if (Test-Path -LiteralPath $userBin) {
        [void]$candidates.Add([pscustomobject]@{ kind = 'user-bin'; command = $userBin; detail = 'checkout installer' })
    }

    $toolchains = Join-Path $ElanHome 'toolchains'
    if (Test-Path -LiteralPath $toolchains) {
        foreach ($dir in Get-ChildItem -LiteralPath $toolchains -Directory -ErrorAction SilentlyContinue) {
            $exe = Join-Path $dir.FullName 'bin\lean-beam-mcp.exe'
            if (Test-Path -LiteralPath $exe) {
                [void]$candidates.Add([pscustomobject]@{
                        kind = 'toolchain'
                        command = $exe
                        detail = "bundled with elan toolchain $($dir.Name) — serves only projects pinned to that installation"
                    })
            }
        }
    }

    $chosen = $candidates | Select-Object -First 1
    [pscustomobject]@{
        Found      = [bool]$chosen
        Command    = if ($chosen) { $chosen.command } else { $null }
        Kind       = if ($chosen) { $chosen.kind } else { $null }
        Detail     = if ($chosen) { $chosen.detail } else { $null }
        Candidates = $candidates
    }
}
