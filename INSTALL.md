# 安裝：給 Codex 與使用者

## Codex 安裝協定

當使用者說「安裝 comfyui-sprite-forge + GitHub 網址」，請依以下程序完成；這不是只安裝單一 SKILL.md 的 repository。

1. **讀取來源。** 取得使用者提供的 repository，先讀 README.md、這份文件與 AGENTS.md。將完整專案 clone／下載到使用者選擇的永久資料夾；未指定時使用合適的專案資料夾，不要把暫存解壓目錄當永久來源。
2. **保留其他安裝。** 確認目的 skills 路徑。只以本專案 `tools/comfyui_forge_install_skills.py` 安裝 `comfyui-forge-*`；不要卸載原版，不要覆蓋它的五個未加前綴目錄、manifest、設定或其他技能。
3. **找 Python 與 ffmpeg。** 找能執行的 Python 3.10+。在此專案建立 `.venv` 並安裝 requirements.txt；依環境正常的授權流程處理網路與檔案權限。不要替換 ComfyUI 自己的 Python。檢查 ffmpeg/ffprobe 的存在與功能；缺少時明確列出，未經使用者授權不要下載外部執行檔。
4. **找使用者的 workflow。** 使用者應已能在本機 ComfyUI 跑 H3。若未提供 API JSON 的位置，請詢問檔案位置；不要猜測另一台電腦的模型路徑，本專案不附工作流，安裝技能不包含安裝 ComfyUI、模型或 custom nodes。
5. **建立私人設定。** 依 docs/WORKFLOW.md 解析 API JSON，建立 local-comfyui/config.local.json，設定正確 bindings、output_node 與模型影格規則。workflow 可以是檔案的絕對路徑，也可相對 config.local.json；不要改動使用者原始 workflow，必要時另存副本。個人設定與 workflow.local.json 已被 .gitignore 排除。
6. **安裝所有技能。** 用選定 Python 執行下方安裝命令，不加 `--skills` 以免漏裝。安裝程式會備份本修改版舊檔、複製 scripts/references/agents、寫獨立 manifest 及 `comfyuiConfig` 指向。這個指向讓已安裝的工具自動找到設定，不需寫入全域 FORGE_* 或 Codex 設定。
7. **分開驗證。** 執行 installer --check、tools/comfyui_forge_test_release.py；用已安裝路徑的 comfyui_forge_media.py --check，再用使用者提供的、尺寸合法的圖片與短提示詞執行 --dry-run。未提供圖片時先完成安裝及唯讀檢查，並說明尚未執行 dry-run；不要宣稱全部完成。只有使用者另外要求生成測試時才 POST GPU 任務。
8. **回報。** 列出永久 repository、Python、skills 路徑、實際安裝的核心與選用技能、config/workflow 路徑、檢查結果及任何缺項，告知開新對話／必要時重啟。不把「skills 檔案安裝成功」混同「ComfyUI 已能生成」或「畫面品質通過」。

如果使用者尚未安裝／啟動 ComfyUI，仍可準備依賴與設定文件，但不能宣稱生成環境通過。不要自動下載模型、安裝 custom nodes 或切換雲端。

## Windows 手動安裝

先將 repository 下載到永久資料夾，在該資料夾開 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item local-comfyui/config.example.json local-comfyui/config.local.json
```

接著依 [WORKFLOW.md](docs/WORKFLOW.md) 編輯 config.local.json 與你自己的 API JSON。不要把例子的 node ID 直接套用到不同工作流。

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --apply --host codex --config local-comfyui/config.local.json
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --check --host codex
.\.venv\Scripts\python.exe tools/comfyui_forge_test_release.py
```

已安裝 skill 位於 `$CODEX_HOME/skills`，若 CODEX_HOME 未設定則是 `$HOME/.codex/skills`。以實際路徑執行：

```powershell
$SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py" --check
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-video2dsprite/scripts/comfyui_forge_video2dsprite.py" doctor
```

上面的 `$SkillsRoot` 是一般腳本變數，沒有修改 HOME 或 CODEX_HOME。

若希望直接執行 venv Python：Windows 使用 `.venv/Scripts/python.exe`，其他環境通常是 `.venv/bin/python`。安裝程式不會將依賴偷偷裝到其他 Python；Codex 應在每次工具呼叫使用選定的 Python。安裝 manifest 的 `project` 欄位可找回 repository 與 `.venv`。

## 更新、移動、指定另一份設定

更新 repository 後重跑 `--apply --host codex --config ...` 與 `--check`。舊的本修改版 skills 會備份，原版仍不動。

若 repository 或 workflow 被移動，先修正 config.local.json，再重跑安裝。已安裝的工具不會自行猜新路徑。

臨時使用其他設定可在**同一次工具呼叫的 shell**中指定：

```powershell
$env:COMFYUI_FORGE_CONFIG = (Resolve-Path local-comfyui/config.local.json).Path
.\.venv\Scripts\python.exe skills/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py --check
```

設定搜尋順序：明確的 COMFYUI_FORGE_CONFIG → 已安裝 skills 根目錄 manifest 的 comfyuiConfig → 從 repository 執行時的 local-comfyui/config.local.json。無設定就停止，不使用範例偷偷生成。明確環境變數指向不存在的檔案時直接報錯，不降級到其他設定。

## 權限與失敗

安裝需要 repository、目的 skills 及其父資料夾的寫入權限（staging／備份在 skills 同層）。首次建立 venv／安裝 Python 套件通常需要網路。唯讀 ComfyUI 檢查需要能連線 localhost；權限被拒絕時記錄實際錯誤與步驟，不宣稱成功，也不要改用雲端。


## 版本來源診斷

`comfyui_forge_doctor.py --offline` 不連線服務，回報實際adapter、Python、設定與manifest路徑、SHA-256及是否符合manifest指向的專案adapter。更新後仍以installer --check檢查三個核心 Skills的檔案同步；版本診斷不能取代完整安裝檢查。正式更新會先備份本專案既有安裝，不覆蓋原版或其他技能。

## 核心範圍與檔名

預設安裝三個角色動畫核心：`comfyui-forge-generate2dmedia`、`comfyui-forge-generate2dsprite`、`comfyui-forge-video2dsprite`。地圖與程式繪圖保留為選用工具，只有明確加 `--include-extras` 或以 `--skills` 指定才安裝。更新時，先前由此專案管理的未選用工具會先備份再移出；原版技能與其他技能不受影響。

Skill 名稱及資料夾使用 `comfyui-forge-`；Python 實體檔名、模組匯入與呼叫統一使用 `comfyui_forge_`，以符合 Python 匯入語法。舊檔不保留轉接殼。執行 `tools/comfyui_forge_test_release.py` 會核對實體入口、批次映射、共用副本及完整測試。
