# Attribution and scope / 原作者與修改說明

本專案是 **Agent Sprite Forge 的非官方修改版**，不是原作者發行的版本。

- 上游專案：https://github.com/0x0funky/agent-sprite-forge
- 上游 LICENSE：https://github.com/0x0funky/agent-sprite-forge/blob/main/LICENSE
- 上游版權聲明：Copyright (c) 2026 0x0funky
- 授權：MIT；完整上游文字保留於根目錄 LICENSE。
- 本修改版的修改與範例素材：Copyright (c) 2026 yuwechang，同樣採用MIT授權；涵蓋examples/內的角色原圖、PNG圖集及GIF動畫。
- 本地修改起點的既有紀錄：`5324342fdfab72430f4e9604f3fe427009f8596d`。此值來自本專案前身的修改紀錄，不表示本發佈資料夾具備完整上游 Git 歷史。

本修改版保留上游的主要離線素材處理程式及相關 references，加入或調整：

1. 唯一本機 ComfyUI 圖生影片 provider、job.json 續取與結果校驗。
2. 移除雲端 API provider、API key 設定與 CLI 生成後備路由。
3. 五個 `comfyui-forge-*` 獨立技能名稱、資料夾、UI metadata與安裝 manifest，支援與原版並存。
4. 本機 workflow bindings、可攜式設定尋找及完整 sibling skills 安裝。
5. 3秒來源影片請求、24fps、32倍數畫布的預設說明與本機動畫處理指引。
6. 本發佈版的安裝、工作流映射、測試與繁體中文文件。

本修改版不附上游歷史技術文件，也不代表保留所有上游功能或已重現其歷史驗證。此次發佈未附上游展示圖片／影片、個人安裝報告、模型權重或執行環境。examples/ 另包含維護者提供的角色測試圖片與成品，素材說明見 examples/README.md。

本儲存庫的原始碼、維護者修改及examples/內提供的圖片與動畫均採用MIT授權，保留各自的版權聲明。未隨專案提供的ComfyUI、Python套件、ffmpeg、模型、第三方custom nodes，以及使用者另外提供或生成的內容，仍依各自適用的授權；本專案不替它們提供額外授權。本專案不附可執行工作流或模型；使用者應自行準備工作流並確認其模型與節點來源、授權。
