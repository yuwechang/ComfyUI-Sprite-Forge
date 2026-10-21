# 本機 H3 工作流設定

**繁體中文** | [简体中文](WORKFLOW.zh-CN.md) | [English](WORKFLOW.en.md) | [日本語](WORKFLOW.ja.md) | [한국어](WORKFLOW.ko.md)

## 工作流格式

使用已能在本機 ComfyUI 執行的 **Export (API) JSON**。頂層以字串節點 ID 為鍵，每個節點包含 `class_type` 與 `inputs`；含頂層 `nodes`、`links` 的畫布格式不適用。

adapter 上傳首圖與可選尾圖，依設定寫入節點輸入，透過 `/prompt` 提交、`/history/{prompt_id}` 查詢結果，再由 `/view` 下載 MP4。

## 設定欄位

以 [config.example.json](../local-comfyui/config.example.json) 建立 `local-comfyui/config.local.json`，依實際工作流填入下列欄位。

所有節點對應使用 `["節點 ID", "input 名稱"]`，節點 ID 為字串。

| 欄位 | 設定依據 |
|---|---|
| `url` | 本機 ComfyUI 位址，支援 HTTP 的 `127.0.0.1`、`localhost` 或 `[::1]` 與自訂 port；不支援登入憑證、proxy 或 redirect。 |
| `workflow` | 使用者的 API JSON 路徑；相對路徑以設定檔所在資料夾解析。Windows 路徑使用 `/` 或 JSON 跳脫的 `\\`。 |
| `output_node` | 實際輸出 MP4 的節點 ID。 |
| `bindings.image` | 首圖 LoadImage 的 `image` input；上傳後寫入 ComfyUI 回傳的檔名。 |
| `bindings.prompt` | 提示詞文字 input。 |
| `bindings.width`、`bindings.height` | 實際控制生成寬高的 input；指定位置原有的連線會被數值取代。 |
| `bindings.length` | 接收整數總影格數的 input。 |
| `bindings.fps` | 可選，影片輸出節點的 fps input；省略時工作流須固定為 24 fps。 |
| `bindings.last_image` | 可選，尾圖 LoadImage 的 `image` input，須搭配 `last_frame_input`。 |
| `last_frame_input` | 實際接收尾圖的節點與 input；未提供尾圖時 adapter 移除此處連線。無尾圖功能時省略此欄位與 `bindings.last_image`。 |
| `bindings.seed` | 可選，亂數種子的節點與 input；省略時自動尋找輸出分支的 `seed`／`noise_seed`，包含其上游連線。 |
| `fps`、`frame_multiple`、`frame_offset`、`frame_minimum` | 固定為 `24`、`17`、`5`、`5`；省略時採用這些值。 |
| `planning.minimum_source_size` | 可選，工作流已驗證的最低輸入尺寸 `[寬, 高]`，供規格工具檢查。 |
| `planning.dimension_multiple` | 可選，規格工具的尺寸對齊倍數，預設 `32`；輸入圖仍須符合 adapter 的 32 倍數限制。 |

## 影格與尺寸限制

來源固定 24 fps，請求時長 `a` 為大於 0、最多 15 秒的數值。總影格數計算如下，`round` 使用 Python 的四捨六入、正中間取偶數規則：

```text
n = max(5, round(a * 24))
frames = min(345, n + (5 - n % 17) % 17)
```

總影格數符合 `17k + 5`，最多 345 幀，實際最長 14.375 秒。`bindings.length` 直接接收此數值。

輸入圖寬高須為 32 的倍數，並符合工作流的最低尺寸。變更已登錄輸入圖的尺寸後，須重新準備 `registration_job`。

## 輸出相容性

adapter 只提交 `output_node` 及其上游相依節點。指定輸出節點的 history 結果須在 `gifs`、`videos` 或 `images` 列表中提供含 `filename`、`subfolder`、`type` 的 `.mp4` 項目；adapter 下載第一個符合的 MP4。

若節點只接受秒數、輸出格式或 history 結構不同，須調整工作流副本或 adapter 後再驗證。

每個新生成任務會為找到的種子輸入寫入同一個非負整數亂數種子；沒有種子欄位則略過。特殊種子範圍或多個獨立種子需求須另行配置。續接任務沿用已提交的工作流與種子。

## 驗證設定

使用專案 `.venv` 的 Python 執行工具，`scripts` 為 `comfyui-forge-generate2dmedia` 的實際安裝目錄下的資料夾：

```text
<Python> <scripts>/comfyui_forge_media.py --check
<Python> <scripts>/comfyui_forge_route_media.py video --route comfyui --reference <輸入圖片> --prompt-file <提示詞文字檔> --duration <請求秒數> --out-dir <工作目錄> --dry-run
```

`--check` 連線本機 API，檢查執行分支的節點類別與部分已知模型欄位選項；`--dry-run` 檢查請求，不連線、不建立輸出目錄。兩者均不生成影片，也不驗證實際畫面品質。

安裝及設定路徑的更新方式見 [INSTALL.md](../INSTALL.md)。
