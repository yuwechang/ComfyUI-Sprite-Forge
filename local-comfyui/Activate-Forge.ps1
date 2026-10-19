param([string]$Config = (Join-Path $PSScriptRoot 'config.local.json'))
$ErrorActionPreference = 'Stop'
$env:COMFYUI_FORGE_CONFIG = (Resolve-Path -LiteralPath $Config).Path
$env:COMFYUI_FORGE_VIDEO_ROUTE = 'comfyui'
