# 本机 ComfyUI 配置文件

[繁體中文](README.md) | **简体中文** | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

本目录提供配置模板；工作流、模型与 ComfyUI 由用户准备。

- `config.example.json`：连接与节点映射的配置格式。节点 ID 按自己的 API JSON 调整，帧数规则采用项目固定值。
- `config.local.json`：根据模板创建的个人配置，已被 Git 忽略。
- `workflow.local.json`：可选的个人工作流位置，已被 Git 忽略；也可在配置中指向其他位置。

工作流须已能在本机 ComfyUI 生成视频。相对工作流路径以配置文件所在文件夹解析。完整配置方法见 [工作流配置](../docs/WORKFLOW.zh-CN.md)。
