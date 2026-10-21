# Codex 安裝說明

## 安裝前提

- Python 3.10+、FFmpeg 與 FFprobe；檢查是否可正常執行，缺少時協助安裝。
- 已能執行 H3 工作流的本機 ComfyUI，以及使用者自己的 API 格式工作流 JSON；未提供時詢問檔案位置。

本專案不附工作流 API JSON。安裝前先讀取 [AGENTS.md](AGENTS.md)。

## 1. 準備專案與 Python 環境

將完整專案 clone／下載到永久資料夾。以下 Windows PowerShell 命令均在專案根目錄執行，`python` 須為 Python 3.10+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

後續使用此虛擬環境的 Python；其他平台路徑為 `.venv/bin/python`。安裝後仍需保留專案與 `.venv`。

## 2. 建立 ComfyUI 設定

首次設定時，複製 `local-comfyui/config.example.json` 為 `local-comfyui/config.local.json`；已有設定則沿用並檢查。

依 [docs/WORKFLOW.md](docs/WORKFLOW.md)，以使用者的 API JSON 設定服務位址、工作流路徑、節點對應與影格規則。工作流路徑可為絕對路徑，或相對於設定檔所在資料夾；需要調整工作流時另存副本。

## 3. 安裝三個技能

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --apply --host codex --config local-comfyui/config.local.json
```

此命令完整安裝以下技能，並記錄專案及設定路徑：

- `comfyui-forge-generate2dmedia`
- `comfyui-forge-generate2dsprite`
- `comfyui-forge-video2dsprite`

安裝位置為 `$CODEX_HOME/skills`；未設定 `CODEX_HOME` 時為 `$HOME/.codex/skills`。

## 4. 驗證安裝

檢查安裝檔案並執行離線測試：

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --check --host codex
.\.venv\Scripts\python.exe tools/comfyui_forge_test_release.py
```

從已安裝位置檢查 ComfyUI 設定與連線：

```powershell
$SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py" --check
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-video2dsprite/scripts/comfyui_forge_video2dsprite.py" doctor
```

若使用者提供了符合工作流尺寸限制的圖片與提示詞，再依 [docs/WORKFLOW.md](docs/WORKFLOW.md) 從已安裝位置執行 `--dry-run`，檢查生成請求。

以上檢查不生成影片；實際生成測試需由使用者另外提出。

## 5. 回報結果

回報專案、Python、技能與設定路徑，以及各項檢查結果和未完成項目。提醒使用者開啟新的 Codex 對話以載入技能。

## 更新與搬移

更新專案後，重跑安裝命令與驗證；安裝程式會備份本專案既有技能。專案或工作流搬移後，修正設定路徑並重新安裝。
