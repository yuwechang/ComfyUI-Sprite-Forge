# Contributing

請先讀 README.md、AGENTS.md 與 NOTICE.md。本修改版的範圍是本機 ComfyUI 生成和離線素材處理；不要重新加入雲端 provider、API key 或 CLI 生成後備，也不要改回原版的技能名稱。

修改後執行 `python tools/test_release.py`。新增 workflow 支援時提供不含模型、私有路徑或憑證的小型 API JSON fixture 與離線測試，說明節點、總影格規則及輸出 history 形狀。需要 GPU 的測試應另外標示與取得使用者授權，不放進預設離線測試。

維持五個 sibling skills 的相對路徑、獨立 manifest、原版並存測試及上游版權聲明。更新根文件、skills 與程式時一併調整相關使用說明。
