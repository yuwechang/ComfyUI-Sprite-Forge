# ComfyUI-Sprite-Forge

**基於 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) 的非官方修改版。** 原作者為 **0x0funky**；本專案不是原作者或 ComfyUI／模型作者的官方產品，也不表示獲得其背書。原專案的 MIT 授權與版權聲明保留於 [LICENSE](../LICENSE)，修改與第三方範圍見 [NOTICE.md](../NOTICE.md)。

把你的角色圖片交給 Codex，透過你自己電腦上的 **ComfyUI 圖生影片工作流**產生動作，再以本機工具去背、選取循環、縮放並輸出透明動畫。**唯一生成來源是本機 ComfyUI；不包含雲端 provider、API key 讀取或 Codex／Grok CLI 生成後備路由。**

## 先決條件

1. 自行安裝並啟動本機 ComfyUI，預設 API 是 `http://127.0.0.1:8188`。
2. **你的 ComfyUI 必須已能正常執行你要使用的 MiniMax H3 圖生影片 workflow**：模型、custom nodes、顯示記憶體與相依環境都需自行備妥。請先在 ComfyUI 介面成功生成影片，再接入此工具。
3. Python **3.10+**，以及 `requirements.txt` 內的 NumPy、Pillow、SciPy；建議使用專用 virtual environment，不要修改 ComfyUI 自己的 Python。
4. `ffmpeg` 與 `ffprobe` 可由 PATH 找到（5.1+）；透明 WebM 需 VP9 支援，packed MP4 額外需要 libx264。可用 `video2dsprite.py doctor` 檢查。
5. 已安裝、可使用本機檔案與 Python 工具的 Codex。

**不附模型權重、不自動下載模型、不安裝或修改 ComfyUI。** 範例 workflow 的 H3／FL2VA／SelfLift 檔名是本地測試環境使用的名稱，**不代表已確認官方模型來源、授權或適用於每一套 H3 安裝**。使用不同 workflow 時請依下一節設定，不能只替換模型檔名就假設相容。

## 交給 Codex 安裝（建議）

發佈到 GitHub 後，把下列訊息交給朋友的 Codex，將「你的帳號」換成實際網址：

> 安裝 comfyui-sprite-forge https://github.com/你的帳號/ComfyUI-Sprite-Forge 。請先讀取這個 repository 的 README.md、INSTALL.md 與 AGENTS.md，保留完整專案，安裝全部五個 comfyui-forge-* skills，不要覆蓋原版 Agent Sprite Forge 或其他技能。我的本機 ComfyUI 已能跑 H3；請檢查並設定我的 API-format workflow。找不到 workflow 時先問我位置。安裝後做唯讀節點／模型檢查及 dry-run；不要自動下載模型或提交 GPU 生成。

此網址目前只是格式範例；本機準備專案不等於已建立 GitHub repository。**安裝用的 Codex 需要能存取該網址、安裝目錄及依賴。** 私有 repository 還需要朋友自己的讀取權限。詳見 [INSTALL.md](../INSTALL.md) 的安裝協定與手動步驟。

## 使用自己的 workflow

1. 從 ComfyUI **匯出 API 格式 JSON**，不是含 `nodes`／`links` 的一般 UI workflow。
2. 複製 `local-comfyui/config.example.json` 為 `config.local.json`，把 `workflow` 指向自己的 API JSON。
3. 依實際節點 ID 設定首圖、提示詞、寬高、總影格數及 MP4 輸出節點；可選擇設定尾圖與 fps。
4. 用 `--config` 安裝，再執行 `comfyui_media.py --check` 與 `route_media.py ... --dry-run`。

**完整範例、逐欄解釋、不同節點結構的限制： [docs/WORKFLOW.md](WORKFLOW.md)。** Codex 可以協助讀取你匯出的 JSON 並建立 bindings，但不能保證任意 workflow 不經調整就能使用。

## 安裝命令摘要

在完整 repository 根目錄執行；先備妥 workflow 與 `config.local.json`：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/install_skills.py --apply --host codex --config local-comfyui/config.local.json
.\.venv\Scripts\python.exe tools/install_skills.py --check --host codex
```

安裝程式會把**五個完整 sibling skill 目錄**複製到 `$CODEX_HOME/skills`（未設定時為 `~/.codex/skills`），不是只複製 SKILL.md；原有同名修改版會先備份，再以 SHA-256 清單檢查一致性。設定檔的絕對路徑記錄在獨立 manifest，**不需要修改全域環境變數或 Codex config.toml**。安裝後請開新對話；仍顯示舊清單時重新啟動 Codex。

安裝完成後保留 repository 與 `.venv`；移動資料夾後需以新位置重新安裝。你也可明確用 `COMFYUI_FORGE_CONFIG` 暫時指定另一份設定，但不要沿用原版 `FORGE_*` 變數。

## 怎麼用

> 使用 comfyui-forge-video2dsprite，以這張圖片製作朝右的原地跑步循環。來源影片約 3 秒，遊戲播放長度 1 秒，輸出 128×128、8 fps 的透明動畫，附 GIF 預覽。保持角色外觀、固定鏡頭，不新增特效。

目前預設來源為：**3 秒請求、24 fps、寬高為 32 的倍數**。範例 H3 workflow 依 `17k+5` 規則對齊為 **73 格，約 3.04 秒**；實際限制依你自己的 workflow。原片尺寸不是輸出 sprite 的尺寸，角色會等比例縮放到透明畫布。

遊戲長度與格數另算：1 秒 × 8 fps = 8 格，每格 125 ms。GIF 有 10 ms 時間與二值透明度限制；遊戲請優先使用透明 PNG 與動畫設定，或支援 Alpha 的影片格式。參見 [docs/USAGE.md](USAGE.md)。

## 與原版並存

| 本修改版 skill | 功能 |
|---|---|
| `comfyui-forge-video2dsprite` | 圖生影片、去背、動作循環與透明動畫 |
| `comfyui-forge-generate2dmedia` | 唯一的本機 ComfyUI 生成入口與任務續取 |
| `comfyui-forge-generate2dsprite` | 處理現成 sprite 圖片並封裝 |
| `comfyui-forge-generate2dmap` | 處理現成地圖素材與地圖資料 |
| `comfyui-forge-codeart2d` | 明確要求時使用的離線程式圖形工具，不作生成後備 |

安裝紀錄為 `.comfyui-sprite-forge.install.json`。原版未加前綴的技能目錄與 `.agent-sprite-forge.install.json` 都不由此安裝程式管理。只有生成路由是 ComfyUI：**未配置靜態圖片生成 workflow，請自行提供角色／地圖原圖**。

## 驗證與界線

- `python tools/test_release.py`：執行發佈支援的離線測試，不連網、不提交 GPU 任務。
- `comfyui_media.py --check`：本機節點及模型檔名檢查，不代表顯示記憶體、工作流執行或美術品質已通過。
- `--dry-run`：檢查輸入與設定，不上傳圖片、不建立任務。
- `job.json` 為 pending 時續取；unknown 時先查 queue/history；done 時驗證產物 SHA-256，不為安裝驗證重複生成。
- Adapter 僅接受本機 HTTP loopback，停用 proxy 並拒絕 redirect；這不限制你自行安裝的 ComfyUI custom nodes 的網路行為。
- 動作、外觀、循環接縫與去背邊緣都要實際觀看。技術檢查通過不代表美術正式驗收。

目前保留 Windows PowerShell launcher；Python 核心可在符合依賴的環境使用，但其他作業系統尚未完成實機驗證。歷史上游測試與目前發佈測試的差別見 [docs/VALIDATION.md](VALIDATION.md)。
