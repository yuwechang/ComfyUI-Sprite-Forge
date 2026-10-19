# ComfyUI-Sprite-Forge

[繁體中文](README.md) | **简体中文** | [日本語](README.ja.md) | [한국어](README.ko.md) | [English](README.en.md)

**把角色图片变成游戏用的透明动画，让 Codex 帮你操作。**

例如：上传一张角色图，制作跑步动作，再输出透明 PNG 图集与 GIF 预览。视频由你电脑上的 **ComfyUI** 生成，不需要云端生成 API key。

这是基于 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) 的**非官方修改版**。原作者为 **0x0funky**，保留原项目的 [MIT 许可证](LICENSE)。本版使用独立名称，可以和原版一起安装。

## 先准备这两样

1. **Codex**：可以读取你电脑上的文件、执行工具。
2. **本地 ComfyUI**：已经安装好，并且**能用 MiniMax H3 工作流成功生成视频**。

本项目不附带模型，也不会帮你安装 ComfyUI。其他程序依赖可以请 Codex 协助检查与安装。

## 怎么安装？

把下面这段话粘贴给你的 Codex：

> 安装 comfyui-sprite-forge：https://github.com/yuwechang/ComfyUI-Sprite-Forge 。请按项目的安装说明安装全部技能，保留原版和其他技能。我的本地 ComfyUI 已能运行 H3；请协助配置我的工作流并检查兼容性。需要文件位置时再问我，不要自动下载模型或开始生成视频。

安装完成后，**打开一个新的 Codex 对话**再使用。

## 我有自己的工作流，怎么办？

可以使用自己的工作流。先从 ComfyUI 导出 **API 格式的 JSON 文件**，再把文件交给 Codex，说：

> 请让 ComfyUI-Sprite-Forge 使用这份工作流，协助配置并检查兼容性。

Codex 会按项目说明找出需要连接的节点。不同工作流可能需要调整；如果你不知道怎么导出，也可以先请 Codex 指引。

## 怎么制作动画？

上传角色图片，对 Codex 说：

> 使用 comfyui-forge-video2dsprite，把这张角色图制作成朝右的原地跑步循环。游戏播放长度 1 秒，输出 128×128、8 fps 的透明动画，并附 GIF 预览。固定镜头，不添加特效。

默认会先生成约 **3 秒**的源视频，再挑选合适的动作帧。上面的例子会输出 **8 帧动画，每帧播放 0.125 秒，合计 1 秒**。

角色会等比例缩放，放进透明画布，不会把整个视频硬拉成正方形。生成结果仍需检查外观、动作与去背质量。

## 想看细节？

- [完整安装说明](INSTALL.md)：也供负责安装的 Codex 阅读。
- [自己的工作流如何配置](docs/WORKFLOW.md)
- [使用与动画规格](docs/USAGE.md)
- [原作者与修改说明](NOTICE.md)
- [上传 GitHub 前的步骤](PUBLISH.md)

这些详细文档目前以繁体中文编写，可以请 Codex 用你熟悉的语言解释。

本版目前需要你提供原始图片，尚未配置静态图片生成。模型与第三方节点的来源、许可证请自行确认。
