# Attribution and scope / 原作者與修改說明

本專案是 **Agent Sprite Forge 的非官方修改版**，不是原作者發行的版本。

- 上游專案：https://github.com/0x0funky/agent-sprite-forge
- 上游 LICENSE：https://github.com/0x0funky/agent-sprite-forge/blob/main/LICENSE
- 上游版權聲明：Copyright (c) 2026 0x0funky
- 授權：MIT；完整上游文字保留於根目錄 LICENSE。
- 本地修改起點的既有紀錄：`5324342fdfab72430f4e9604f3fe427009f8596d`。此值來自本專案前身的修改紀錄，不表示本發佈資料夾具備完整上游 Git 歷史。

本修改版保留上游的主要離線素材處理程式及相關 references，加入或調整：

1. 唯一本機 ComfyUI 圖生影片 provider、job.json 續取與結果校驗。
2. 移除雲端 API provider、API key 設定與 CLI 生成後備路由。
3. 五個 `comfyui-forge-*` 獨立技能名稱、資料夾、UI metadata與安裝 manifest，支援與原版並存。
4. 本機 workflow bindings、可攜式設定尋找及完整 sibling skills 安裝。
5. 3秒來源影片請求、24fps、32倍數畫布的預設說明與本機動畫處理指引。
6. 本發佈版的安裝、工作流映射、測試與繁體中文文件。

`docs/UPSTREAM_CHANGELOG.md` 是歷史上游文件，不代表本修改版仍保留其中所有雲端功能或已重現所有歷史驗證。此次發佈沒有附上游展示圖片／影片、個人測試素材、個人安裝報告、模型權重或執行環境。

ComfyUI、Python 套件、ffmpeg、模型、第三方 custom nodes、使用者輸入及生成內容各有其來源與授權；本專案 MIT LICENSE 不替它們提供額外授權。隨附 workflow 中的 H3、FL2VA、SelfLift 與模型檔名只記錄本機設定，不宣稱官方來源、取得方式、授權或背書。
