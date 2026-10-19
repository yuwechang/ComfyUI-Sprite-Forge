# 驗證範圍

本發佈版的支援測試入口為 `python tools/test_release.py`。它執行本機provider、唯一本機路由、安裝共存、可攜設定與預覽匯出的離線回歸測試，不需要ComfyUI或GPU，也不會連線雲端。

2026-10-19 發佈準備驗證：26項聚焦離線測試通過；28份vendored相依檔案與shared canonicals一致；88個Python檔案通過語法解析；五個SKILL.md的名稱／description與資料夾相符。另以既有角色影格確認128×128、8格、1秒透明PNG/APNG/GIF匯出。範例workflow的本機節點與模型檔名唯讀檢查通過，沒有提交新GPU任務。此結果僅代表該次Windows環境，不代表朋友的環境已驗證。

官方skill-creator quick_validate.py因驗證環境缺少PyYAML未能執行；此版另做五個entrypoint的靜態frontmatter欄位與名稱檢查，不將它描述為完整YAML驗證器通過。

上游歷史測試、展示素材及過去個人實測報告沒有全部帶進此發佈包。不要將本機聚焦測試的通過，宣稱為完整上游pytest套件通過，或保證其他作業系統／模型／custom node版本都能跑。

人工安裝驗收順序：

1. 所有五個namespaced skills、scripts、references與manifest存在。
2. 原版技能與原版manifest未改；installer --check無差異。
3. 清除COMFYUI_FORGE_CONFIG的shell中，已安裝工具能透過自己的manifest找到使用者設定。
4. 用自己的ComfyUI執行--check，缺項如實列出。
5. 提供合法尺寸的測試圖與提示詞，執行--dry-run，不提交任務。
6. 只有在使用者要求時生成一次；後續resume／安裝驗證重用產物。
7. 觀看影片及透明動畫：身份、方向、鏡頭、肢體、循環、腳部接觸與深／淺底去背邊緣。

安裝指向的workflow與設定檔應保留。搬動後需重裝更新指向；範例workflow成功與否不能代替使用者自己的工作流實測。
