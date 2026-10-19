# 上傳 GitHub 前

這個資料夾已整理為可發佈的程式來源；尚未替你建立GitHub repository或推送。README中的「你的帳號」只是清楚標示的網址範例，實際建立repository後應改成你的真實網址。

建議repository名稱：**ComfyUI-Sprite-Forge**。

1. 檢查 README.md、INSTALL.md、NOTICE.md 與原版 MIT LICENSE。不要刪除原作者0x0funky的版權聲明。
2. 執行 `python tools/test_release.py`。測試不需要GPU或ComfyUI。
3. 用 `git status`／`git diff --cached` 檢查要上傳的清單。不要包含.venv、個人config.local.json、workflow.local.json、模型權重、生成媒體、備份與個人報告。
4. 自行建立GitHub repository，取得真實URL，再選擇網頁上傳檔案或使用Git推送。第一次初始化後，若GitHub上已存在README等檔案，先檢查並整合遠端歷史，不要force push覆蓋。
5. README的安裝提示詞填入真實GitHub URL後，將整段交給朋友的Codex。私人repository須另外給朋友讀取權限。

朋友需要的是**整個來源repo**，不是只下載一個SKILL.md。他們也需要自己的本機ComfyUI、能正常跑的H3 workflow、Python依賴和ffmpeg。Codex依INSTALL.md安裝五個技能後，會以他們自己的config與workflow路徑建立manifest，不會複製你的個人安裝路徑。

本專案不含第三方模型或執行環境；examples/ 包含維護者以MIT授權提供的角色測試素材，說明見 examples/README.md。分享workflow範例時，模型名稱仍只表示本機設定，不宣稱官方來源或授權。
