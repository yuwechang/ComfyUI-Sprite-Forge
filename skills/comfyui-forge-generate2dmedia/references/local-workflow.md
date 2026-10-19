# 接入自己的本機 H3 workflow

## 支援範圍

此 adapter 會上傳首圖、可選尾圖，將提示詞、寬高、總影格數與 fps 寫入指定節點，提交到本機 `/prompt`，輪詢 `/history/{prompt_id}`，再由 `/view` 下載 MP4。它不會操作 ComfyUI 畫布 UI，也不會替你安裝模型。

你的工作流須已能在 ComfyUI 正常執行。不同 custom node 版本、wrapper、音訊分支與模型封裝可能有不同限制。**可設定 bindings 不等於支援任意 JSON**：不支援的結構需要修改 workflow 副本或 adapter，並再次測試。

## 1. 匯出 API 格式

從你的 ComfyUI 匯出 **Export (API)** JSON（不同版本可能需先開啟開發者選項）。有效格式大致如下：

```json
{
  "11": { "class_type": "LoadImage", "inputs": { "image": "first.png" } },
  "7": { "class_type": "PrimitiveStringMultiline", "inputs": { "value": "prompt" } }
}
```

這只是兩個節點的格式示意，不是可生成影片的完整 workflow。一般 UI 格式含頂層 `nodes`、`links`，adapter 會拒絕。

可以將真正 API JSON 留在使用者原資料夾，或另存 `local-comfyui/workflow.local.json`。個人模型檔名與路徑可能不適合公開；此檔預設被 Git 忽略。

## 2. 建立設定

先複製 config.example.json 成 config.local.json。以下 ID 來自隨附範例，**需要換成你的實際節點 ID 與 inputs 名稱**：

```json
{
  "url": "http://127.0.0.1:8188",
  "workflow": "workflow.local.json",
  "output_node": "48",
  "fps": 24,
  "frame_multiple": 17,
  "frame_offset": 5,
  "bindings": {
    "image": ["11", "image"],
    "prompt": ["7", "value"],
    "width": ["349", "width"],
    "height": ["349", "height"],
    "length": ["349", "length"],
    "fps": ["48", "frame_rate"],
    "last_image": ["12", "image"]
  },
  "last_frame_input": ["349", "last_frame"]
}
```

`workflow.local.json` 依 **config.local.json 的資料夾**解析，不依 shell 工作目錄。也可以使用自己的絕對路徑。Windows JSON 的反斜線必須寫成 `\\`，或改用 `/`。

| 欄位 | 如何找你的值 |
|---|---|
| `url` | 本機 ComfyUI API 位址。只允許 HTTP 的 127.0.0.1、localhost 或 ::1；可換本機 port，不支援遠端／雲端 URL、登入憑證、proxy 或 redirect。 |
| `output_node` | 實際輸出 MP4 的節點 ID，不是 sampler 或 latent 節點。範例是 VHS_VideoCombine，format 為 video/h264-mp4，save_output=true。 |
| `bindings.image` | LoadImage 的節點 ID 與 `image` input。adapter 上傳後會換成 ComfyUI 回傳的檔名。 |
| `bindings.prompt` | 寫入文字的節點 ID 與 input 名稱。例如 primitive 的 value，或 CLIPTextEncode 的 text。 |
| `bindings.width/height` | 真正供 latent／H3 圖生影片節點使用的寬高 input。adapter 會覆寫該 input 的數值，即使原本是連線。 |
| `bindings.length` | 接受**總影格數**的 input，不是秒數或單純 batch size。若你的節點只收秒數，需先改 workflow 或 adapter。 |
| `bindings.fps` | 可選，輸出合成器的 fps input。若省略，請在 workflow 自行固定成與設定 fps 相同的值。 |
| `last_image` / `last_frame_input` | 可選，尾圖 loader 的 image input，以及真正消費尾圖的 input。沒用尾圖時 adapter 會移除這個消費端連線。 |

沒有尾圖功能時，**同時刪掉 bindings.last_image 與 last_frame_input**，也不要使用 --last-frame。節點的 ID 一律為字串，例如 `"349"`。

範例 `17k+5` 表示總影格數對齊至 5、22、39、56、73……，3 秒 ×24 fps =72 格，向上對齊為73格。這是目前 H3 範例的設定，不是所有模型的通用規則。自己的工作流若不同，應依節點規則設定 frame_multiple/frame_offset，例如允許任意正整數時為1與0。不要憑猜測修改。

目前工具仍要求輸入圖寬高為32的倍數。先等比例縮放角色並留背景空間，再送入；不要將角色硬拉到另一個長寬比。已記錄 registration_job 的輸入若改尺寸，需要重新準備登錄資料。

## 3. 確認輸出與節點

adapter 只提交 output_node 的祖先節點，捨棄不相連的 UI helper。不會重命名模型或自動修復節點。`--check` 比較執行分支的 class_type，並檢查部分已知模型欄位的本機選項；其他 custom node 的模型欄位不一定被此檢查涵蓋。

目前輸出必須在指定節點的 history output 中，以 gifs/videos/images 列表回傳含 filename/subfolder/type 的 **.mp4**。如果自己的 SaveVideo 節點使用不同 history 結構、只回傳 .webm、包含多個影片或只顯示預覽，需改用相容 MP4 輸出或修改 adapter；此版本下載第一個符合的 MP4。

帶身份驗證的 API node 或遠端生成節點不符合本專案本機生成的定位。custom nodes 的網路行為由你自己的 ComfyUI 管理，adapter 的 loopback 限制不是全系統網路防火牆。

## 4. 安裝與唯讀驗證

```powershell
.\.venv\Scripts\python.exe tools/install_skills.py --apply --host codex --config local-comfyui/config.local.json
.\.venv\Scripts\python.exe skills/comfyui-forge-generate2dmedia/scripts/comfyui_media.py --check
.\.venv\Scripts\python.exe skills/comfyui-forge-generate2dmedia/scripts/route_media.py video --route comfyui --reference input.png --prompt-file prompt.txt --duration 3 --out-dir outputs/first-take --dry-run
```

input.png 與 prompt.txt 必須是你提供或準備的實際檔案。--dry-run 不連線、不建立輸出資料夾，--check 會讀取本機 API 但不生成。通過後，只有你要求實測生成時才移除 --dry-run。

## 可以交給朋友的 Codex 的提示詞

> 我的 ComfyUI 已能正常執行這份 H3 API workflow：〈我的 JSON 路徑〉。請讀取 docs/WORKFLOW.md，建立此專案的 config.local.json，找出首圖、提示詞、寬高、總影格、fps與MP4輸出節點。保留原始 JSON；不相容時先說明需要調整的節點。安裝全部五個 skills，然後做 --check 與 dry-run，不要下載模型或提交 GPU 任務。
