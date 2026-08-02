[CmdletBinding()]
param(
  [switch]$WithDev,
  [switch]$SkipPython,
  [switch]$SkipNode,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = $null

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
  try {
    & $py.Source -3.11 --version *> $null
    if ($LASTEXITCODE -eq 0) { $Python = @($py.Source, '-3.11') }
  } catch {}
}
if (-not $Python) {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) { $Python = @($pythonCmd.Source) }
}
if (-not $Python) {
  throw 'Python 3.11+ is required. Install Python, then rerun scripts/bootstrap.ps1.'
}

$args = @((Join-Path $PSScriptRoot 'bootstrap.py'))
if ($WithDev) { $args += '--with-dev' }
if ($SkipPython) { $args += '--skip-python' }
if ($SkipNode) { $args += '--skip-node' }
if ($DryRun) { $args += '--dry-run' }

Write-Host "[bootstrap] invoking Python: $($Python -join ' ')"
if ($Python.Count -eq 2) {
  & $Python[0] $Python[1] @args
} else {
  & $Python[0] @args
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
