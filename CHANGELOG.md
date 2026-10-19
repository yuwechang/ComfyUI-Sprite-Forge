# Changelog

## 0.1.0 — GitHub 發佈準備版（2026-10-19）

- 以 ComfyUI-Sprite-Forge 名稱整理非官方修改版，保留上游 MIT LICENSE 與來源說明。
- 五個 comfyui-forge-* skills 與獨立 manifest，原版未加前綴技能不由本 installer 管理。
- 生成僅走本機 ComfyUI；移除雲端 provider、API key 讀取與 CLI 生成後備。
- 支援使用者提供 API-format workflow 與節點 bindings；未配置靜態圖片生成。
- installer 記錄本機設定位置，已安裝 adapter 自動尋找，不需全域 Codex 設定。
- 移除個人路徑與展示素材，補齊 README、INSTALL、WORKFLOW、AGENTS 與發佈測試指令。

上游歷史記錄另見 docs/UPSTREAM_CHANGELOG.md。
