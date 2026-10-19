param(
    [ValidateSet('Check','DryRun','Generate','Resume')][string]$Action = 'Check',
    [string]$Config,
    [string]$Reference,
    [string]$PromptFile,
    [string]$LastFrame,
    [string]$OutDir,
    [int]$Duration = 3,
    [int]$TimeoutSeconds = 1800,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if ($Config) { $env:COMFYUI_FORGE_CONFIG = (Resolve-Path -LiteralPath $Config).Path } elseif (Test-Path (Join-Path $PSScriptRoot 'local-comfyui\config.local.json')) { $env:COMFYUI_FORGE_CONFIG = Join-Path $PSScriptRoot 'local-comfyui\config.local.json' }
$providerScript = Join-Path $PSScriptRoot 'skills\comfyui-forge-generate2dmedia\scripts\comfyui_media.py'
$routerScript = Join-Path $PSScriptRoot 'skills\comfyui-forge-generate2dmedia\scripts\route_media.py'
if ($Action -eq 'Check') {
    & $Python $providerScript --check
    exit $LASTEXITCODE
}
if (-not $OutDir) { throw '-OutDir is required' }
if ($Action -eq 'Resume') {
    & $Python $providerScript --resume $OutDir --timeout $TimeoutSeconds
    exit $LASTEXITCODE
}
if (-not $Reference -or -not $PromptFile) { throw '-Reference and -PromptFile are required' }
$routeArgs = @('video','--route','comfyui','--reference',$Reference,'--prompt-file',$PromptFile,
    '--duration',$Duration,'--out-dir',$OutDir,'--timeout',$TimeoutSeconds)
if ($LastFrame) { $routeArgs += @('--last-frame',$LastFrame) }
if ($Action -eq 'DryRun') { $routeArgs += '--dry-run' }
& $Python $routerScript @routeArgs
exit $LASTEXITCODE
