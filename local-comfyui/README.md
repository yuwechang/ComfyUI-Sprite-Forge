# 本機 ComfyUI 設定檔

**繁體中文** | [简体中文](README.zh-CN.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

本目錄提供設定範本；工作流、模型與 ComfyUI 由使用者準備。

- `config.example.json`：連線與節點對應的設定格式。節點 ID 依自己的 API JSON 調整，影格規則採專案固定值。
- `config.local.json`：由範本建立的個人設定，已被 Git 忽略。
- `workflow.local.json`：可選的個人工作流位置，已被 Git 忽略；也可在設定中指向其他位置。

工作流須已能在本機 ComfyUI 生成影片。相對工作流路徑以設定檔所在資料夾解析。完整設定方式見 [工作流設定](../docs/WORKFLOW.md)。
