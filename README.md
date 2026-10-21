# ComfyUI-Sprite-Forge

**繁體中文** | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [English](README.en.md)

**把角色圖片變成遊戲用的透明動畫，讓 Codex 幫你操作。**

例如：上傳一張角色圖，製作跑步動作，再輸出透明 PNG 圖集與 GIF 預覽。影片由你電腦上的 **ComfyUI** 生成，不需要雲端生成 API key。

本專案是基於 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) 的**非官方修改版**，專注於 video2sprite 角色動畫流程。影片生成僅連接**本機 ComfyUI**，已移除所有雲端 API 與本機 CLI 生成服務的呼叫，並保留完成透明角色動畫所需的前後處理功能。同時改進規格設定、動作與構圖評估、生成驗收、重試決策及取幀節奏，讓整個製作流程更清楚、可控。

本修改版不包含原版的 **generate2dmap、codeart2d**，也不提供其他獨立素材生成或雲端影片生成服務。若需要地圖、程式繪圖，或透過雲端 API 生成影片等功能，請另行安裝原版 **Agent Sprite Forge**。兩者使用獨立的技能名稱、目錄與安裝紀錄，可同時安裝；各自使用自身程式，不互相覆蓋、干擾或呼叫。

原作者為 **0x0funky**，本專案保留原版的 [MIT 授權](LICENSE)。

## 看看範例

可以直接用 [sample-character.png](examples/sample-character.png) 測試，也可以換成自己的角色圖片。

| 原始角色圖 | 跑步 GIF 預覽 |
|---|---|
| <img src="examples/sample-character.png" alt="綠底角色原圖" width="220"> | <img src="examples/sample-character-run-preview.gif" alt="透明跑步循環" width="128"> |

成品為 **128×128、8 格、8 fps，循環 1 秒**。透明 PNG 圖集：

![8格透明跑步圖集](examples/sample-character-run-spritesheet.png)

想試跑時，對 Codex 說：「使用專案 examples/sample-character.png，製作上面規格的跑步循環。」素材說明見 [examples/README.md](examples/README.md)。

## 先準備這兩樣

1. **Codex**：可以讀取你電腦上的檔案、執行工具。
2. **本機 ComfyUI**：已安裝好，並且**能用 MiniMax H3 工作流成功產生影片**。

本專案不附模型，也不會幫你安裝 ComfyUI。其他程式依賴可以請 Codex 協助檢查與安裝。

本專案不附 ComfyUI 工作流；請自行準備已能正常生成影片的 API JSON。

### FFmpeg 安裝（Windows）

本 Skill 需要 FFmpeg 和 FFprobe 來處理影片。

如果尚未安裝，可以從以下網站取得 Windows 版本：

`https://www.gyan.dev/ffmpeg/builds/`

不熟悉安裝方式的話，可以直接把上面的網址交給 Codex，請它協助安裝、設定 PATH，並確認 FFmpeg 和 FFprobe 都能正常執行。

如果已經安裝，就不需要重複安裝。

## 怎麼安裝？

把下面這段話貼給你的 Codex：

> 安裝 comfyui-sprite-forge：https://github.com/yuwechang/ComfyUI-Sprite-Forge 。請依專案的安裝說明安裝全部技能，保留原版和其他技能。我的本機 ComfyUI 已能跑 H3；請協助設定我的工作流並檢查能否使用。需要檔案位置時再問我，不要自動下載模型或開始生成影片。

安裝完成後，**開一個新的 Codex 對話**再使用。

## 我有自己的工作流，怎麼辦？

可以使用自己的工作流。先從 ComfyUI 匯出 **API 格式的 JSON 檔**，再把檔案交給 Codex，說：

> 請讓 ComfyUI-Sprite-Forge 使用這份工作流，協助設定並檢查相容性。

Codex 會依專案說明找出需要連接的節點。不同工作流可能需要調整；如果你不知道怎麼匯出，也可以先請 Codex 指引。

## 怎麼製作動畫？

上傳角色圖片，對 Codex 說：

> 使用 comfyui-forge-video2dsprite，把這張角色圖製作成朝右的原地跑步循環。遊戲播放長度 1 秒，輸出 128×128、8 fps 的透明動畫，並附 GIF 預覽。固定鏡頭，不新增特效。

預設會先生成約 **3 秒**的來源影片，再挑選合適的動作影格。上面的例子會輸出 **8 格動畫，每格播放 0.125 秒，合計 1 秒**。

角色會等比例縮放，放進透明畫布，不會把整張影片硬拉成正方形。生成結果仍需檢查外觀、動作與去背品質。

## 首次使用與交付

第一次先確認最終尺寸與播放長度（預設128×128、1秒），不要求填fps；8fps為初始預設，取幀時在4-16fps間評估，超過16須另行同意，最高24fps。來源只選解析度：1效能512×512、2平衡768×768（預設）、3品質1024×1024；固定24fps，時長依成品的2-3倍自動評估，請求與對齊後實際長度皆不超過15秒。同一對話可沿用，但每次生成前都列出當次最終／來源規格。所有引導使用你的對話語言。

來源影片用於取得多次完整動作擇優，不代表最終播放3秒或重複3次。標準交付為ZIP（選定PNG影格、透明動畫圖集、GIF、來源影片），並在對話展示預覽；JSON、日誌等留在工作目錄。

## 想看細節？

- [完整安裝說明](INSTALL.md)：也提供給負責安裝的 Codex 閱讀。
- [自己的工作流如何設定](docs/WORKFLOW.md)
- [使用與動畫規格](docs/USAGE.md)
- [原作者與修改說明](NOTICE.md)

你可以使用附帶的測試圖片，或提供自己的角色圖；本版尚未提供靜態圖片生成。模型與第三方節點的來源、授權請自行確認。

本專案的原始碼、修改內容與 examples/ 內的圖片及動畫皆採用 [MIT 授權](LICENSE)。
