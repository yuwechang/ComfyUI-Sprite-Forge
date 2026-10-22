# ComfyUI-Sprite-Forge

[繁體中文](README.md) | **简体中文** | [日本語](README.ja.md) | [한국어](README.ko.md) | [English](README.en.md)

**把角色图片变成游戏用的透明动画，让 Codex 帮你操作。**

例如：上传一张角色图，制作跑步动作，再输出透明 PNG 图集与 GIF 预览。视频由你电脑上的 **ComfyUI** 生成，不需要云端生成 API key。

本项目是基于 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) 的**非官方修改版**，专注于 video2sprite 角色动画流程。视频生成仅连接**本地 ComfyUI**，已移除所有云端 API 与本地 CLI 生成服务的调用，并保留制作透明角色动画所需的前后处理功能。同时改进规格设置、动作与构图评估、生成结果验收、重试决策及取帧节奏，让整个制作流程更清晰、可控。

本修改版不包含原版的 **generate2dmap、codeart2d**，也不提供其他独立素材生成或云端视频生成服务。若需要地图、程序绘图，或通过云端 API 生成视频等功能，请另行安装原版 **Agent Sprite Forge**。两者使用独立的技能名称、目录与安装记录，可同时安装；各自使用自身程序，不互相覆盖、干扰或调用。

原作者为 **0x0funky**，本项目保留原版的 [MIT 许可证](LICENSE)。

## 看看示例

可以直接用 [sample-character.png](examples/sample-character.png) 测试，也可以换成自己的角色图片。

| 原始角色图 | 跑步 GIF 预览 |
|---|---|
| <img src="examples/sample-character.png" alt="绿底角色原图" width="220"> | <img src="examples/sample-character-run-preview.gif" alt="透明跑步循环" width="128"> |

成品为 **128×128、8 帧、8 fps，循环 1 秒**。透明 PNG 图集：

![8帧透明跑步图集](examples/sample-character-run-spritesheet.png)

这是单行排版示例；目前标准交付的 8 帧图集为 4 列、2 行。

## 使用前准备

1. **Codex**：可以读取你电脑上的文件、执行工具。
2. **本地 ComfyUI（需要生成视频时）**：已经安装好，并且**能用 MiniMax H3 工作流成功生成视频**。

本项目不附带模型，也不会帮你安装 ComfyUI。其他程序依赖可以请 Codex 协助检查与安装。

本项目不附带 ComfyUI 工作流；请自行准备已经能够正常生成视频的 API JSON。

## FFmpeg 安装（Windows）

本 Skill 需要 FFmpeg 和 FFprobe 来处理视频，把下面这句话发给你的 Codex：

> 请检查我的 Windows 电脑是否已安装且能正常运行 FFmpeg 和 FFprobe，如果尚未安装，请从 https://www.gyan.dev/ffmpeg/builds/ 下载并协助安装、设置 PATH，再确认两者都能正常运行，已安装的工具无需重复安装。

## 本 Skill 怎么安装？

把下面这段话粘贴给你的 Codex：

> 安装 comfyui-sprite-forge：https://github.com/yuwechang/ComfyUI-Sprite-Forge 。请按项目的安装说明安装全部技能。我的本地 ComfyUI 已能运行 H3；请协助配置我的工作流并检查兼容性。这次只做安装、配置与检查，不下载模型或生成视频。

安装完成后，**打开一个新的 Codex 对话**再使用。

## 我有自己的工作流，怎么办？

可以使用自己的工作流。先从 ComfyUI 导出 **API 格式的 JSON 文件**，再把文件交给 Codex，说：

> 请让 ComfyUI-Sprite-Forge 使用这份工作流，协助配置并检查兼容性。

Codex 会按项目说明找出需要连接的节点。不同工作流可能需要调整；如果你不知道怎么导出，也可以先请 Codex 指引。

## 怎么制作动画？

上传角色图片，对 Codex 说：

> 使用 comfyui-forge-video2dsprite，把这张角色图制作成朝右的原地跑步循环。

已有视频也可以直接交给 Codex，处理成透明角色动画；这种情况不需要生成源视频。

## 首次使用与交付

首次使用时，你可以选择成品尺寸与播放时长，默认为 **128×128、1 秒**。fps 可由 Codex 根据动作评估，通常为 **4–16 fps**；超过 16 fps 会先征得你的同意，最高 24 fps。

源视频可选 **512×512（性能）、768×768（平衡，默认）或 1024×1024（质量）**。源视频固定为 24 fps，时长按成品播放时长的 2–3 倍安排，请求与帧对齐后的实际时长均不超过 15 秒。同一对话可沿用已确认的设置，生成前会提供成品与源视频的规格摘要。

源视频以取得 2–3 次完整动作供比较为目标；有一组完整且合格的动作就足够，成品只选其中一组。标准ZIP只含选定PNG帧、透明动画图集、GIF及来源视频；对话展示预览，JSON、日志等留在工作目录。

## 想看细节？

- [完整安装说明](INSTALL.zh-CN.md)
- [自己的工作流如何配置](docs/WORKFLOW.zh-CN.md)
- [使用与动画规格](docs/USAGE.zh-CN.md)
- [原作者与修改说明](NOTICE.zh-CN.md)
