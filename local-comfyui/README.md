# 接入使用者自己的 ComfyUI

這裡只有設定範本，沒有附帶工作流、模型或 ComfyUI 安裝程式。

- `config.example.json`：連線與節點 bindings 的格式範本。節點 ID 與影格規則僅為示意，請依自己的 API JSON 調整。
- `config.local.json`：依範本建立的個人設定，已被 Git 忽略。
- `workflow.local.json`：可選的個人工作流存放位置，已被 Git 忽略。也可在設定中指向其他位置的 API JSON。

請自行準備已能正常生成影片的本機 ComfyUI 與工作流。工作流路徑相對於設定檔解析；接入方法見 [WORKFLOW.md](../docs/WORKFLOW.md)。缺少私人設定時工具會停止，不會拿範例自動生成。
