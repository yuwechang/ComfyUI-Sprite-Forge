# 原作者與修改說明

## 來源與授權

本專案是基於 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) 修改的非官方版本。

- 原作者：0x0funky，Copyright (c) 2026 0x0funky。
- 本版修改與範例素材：yuwechang，Copyright (c) 2026 yuwechang。
- 專案原始碼、本版修改及 `examples/` 中提供的角色原圖、PNG 圖集與 GIF 動畫均採用 MIT 授權，完整條款與版權聲明見 [LICENSE](LICENSE)。
- 範例素材說明見 [examples/README.md](examples/README.md)。

## 本版修改範圍

本版專注於本機 ComfyUI 角色動畫製作，包含三個技能：

| 技能 | 用途 |
|---|---|
| `comfyui-forge-generate2dmedia` | 本機 ComfyUI 圖生影片、工作流檢查與任務續接。 |
| `comfyui-forge-generate2dsprite` | 角色參考圖片的檢查、去背與輸入準備。 |
| `comfyui-forge-video2dsprite` | 影片轉透明動畫、動作選格、節奏調整與成品交付。 |

相較於上游，本版的主要調整包括：

- 影片生成統一使用本機 ComfyUI，移除雲端 API、API key 設定與 CLI 生成後備路由。
- 使用獨立技能名稱、目錄與安裝紀錄，支援與原版並存。
- 提供使用者工作流的節點對應、設定路徑解析，以及生成任務續接與結果校驗。
- 加入規格規劃、影格對齊與專案偏好保存，依使用者語言確認規格與說明結果。
- 加入動作首圖評估、構圖留白、共同角色尺度、位移處理、動作驗收與重試決策。
- 依完整動作選格、調整播放節奏並保留重要姿勢，於最終成品尺寸檢查預覽與驗收。
- 標準交付為透明 PNG 影格、透明 PNG 圖集、GIF 預覽及來源 MP4，整理為 ZIP。
- 提供安裝與工作流設定文件、離線測試，以及繁體中文、簡體中文、英文、日文、韓文 README；其餘說明文件目前主要為繁體中文。

本版不包含上游的地圖、程式繪圖、獨立靜態圖集／圖示處理及額外引擎傳輸與 runtime 功能，也未設定靜態圖片生成。工作流與模型由使用者自行準備。

ComfyUI、Python 套件、FFmpeg、模型、第三方節點，以及使用者另外提供或生成的內容，依各自適用的授權辦理。
