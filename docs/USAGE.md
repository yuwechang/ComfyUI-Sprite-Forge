# 使用與動畫規格

## 最簡單的呼叫

安裝並開新對話後，明確指名本修改版：

> 使用 comfyui-forge-video2dsprite，讓這張圖片中的角色朝右原地跑步。來源影片約3秒，輸出128×128透明動畫，8格、8fps、遊戲播放1秒，附GIF預覽。不要移動鏡頭、不要新增特效。

角色輸入圖不必已經是128×128。原片畫布與最終sprite cell不同：先保留角色比例、動作空間與登錄資料，再以**單一共同比例**縮放到最終透明畫布。不能將1280×736直接拉成128×128，也不能每格分別裁到角色邊界再各自縮放。

這套流程只生成動作影片；原圖由你提供。不要在沒有圖片生成 workflow 的情況下宣稱可以產生全新角色或地圖。

## 來源片與最終動畫

| 參數 | 來源片 | 遊戲動畫範例 |
|---|---|---|
| 尺寸 | 1280×736已在本機範例驗證；寬高為32倍數 | 每格128×128，透明留白 |
| 時間 | 請求3秒，範例對齊成73格約3.04秒 | 1秒 |
| fps | 24 | 8 |
| 選格 | 排除站立、加速、減速片段，挑一個步態循環 | 8格，各125ms |

不要為改變輸出格數重送生成。使用既有影片重新選格即可。所需格數若多於有效來源格數，要明確說明插值或重複格，不能宣稱抽出了更多獨立動作。

## 工具分工

以下路徑都相對於repository；安裝後可用同名namespaced skill目錄下的腳本。

1. `prepare_i2v_input.py prepare`：以現成圖片準備去背、動作留白、提示詞及registration_job。原圖若含綠底且Alpha幾乎不透明，先確認工具沒有把它誤認成已去背；必要時另存RGB副本再key。正式送出前觀看input.png。
2. `route_media.py video --route comfyui --duration 3 ...`：提交一次本機影片任務。
3. `video2dsprite.py process`：解碼與soft matte；檢查matte-report，不要只看命令退出碼。
4. `register_clip.py apply`：固定座標與比例；跑步保留騰空，不把每格雙腳都鎖在地面。如果登錄畫布不夠，擴大透明動作留白，不是把角色逐格縮小。來源影片實際裁掉肢體時需重做影片，不能靠補空白還原。
5. `gait_loop.py select --kind gait --state run`：分析步態並寫selection.json；選擇仍需觀看循環，跑步不使用來回倒播。
6. `finish_frames.py hd --canvas 128x128 ...`：共同比例與canvas；保留圖格名稱及順序。
7. `tools/export_preview.py`：從完成的圖格依選擇抽出指定格數，輸出透明PNG、APNG與GIF預覽。`engine_export.py`可另作遊戲封裝與驗證。

每個腳本的完整參數以 `--help` 與各skill references為準。matte/registration/gait信心警告應如實報告，不以自動檢查取代視覺驗收。

## 預覽匯出

假設finished/frames含與來源selection同順序、同數量的已完成圖格：

```powershell
.\.venv\Scripts\python.exe tools/export_preview.py --frames outputs/finished/frames --selection outputs/loop/selection.json --count 8 --duration 1 --out-dir outputs/delivery
```

只有8張已選好圖格時，可省略--selection，會依檔名順序使用它們。工具不負責去背或縮放；若不是128×128，它會記錄實際尺寸，不假裝已滿足遊戲規格。

GIF預覽每格以10ms為單位，8格／1秒使用120與130ms交替；PNG/APNG及JSON保留125ms。遊戲優先採PNG和時間設定，GIF的二值透明邊緣不代表原PNG的soft alpha品質。

## 中斷與重跑

pending：`comfyui_media.py --resume 原生成資料夾`，不重送。

unknown：先查看本機queue/history與job.json；不要以新資料夾直接重送，因前一任務可能已被接受。

done：resume會校驗既有MP4的SHA-256；重用影片做後處理。

例：`python skills/comfyui-forge-generate2dmedia/scripts/comfyui_media.py --resume outputs/take-01`。
