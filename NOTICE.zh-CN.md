# 原作者与修改说明

[繁體中文](NOTICE.md) | **简体中文** | [English](NOTICE.en.md) | [日本語](NOTICE.ja.md) | [한국어](NOTICE.ko.md)

## 来源与授权

本项目是基于 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) 修改的非官方版本。

- 原作者：0x0funky，Copyright (c) 2026 0x0funky。
- 本版修改与示例素材：yuwechang，Copyright (c) 2026 yuwechang。
- 项目源代码、本版修改及 `examples/` 中提供的角色原图、PNG 图集与 GIF 动画均采用 MIT 许可，完整条款与版权声明见 [LICENSE](LICENSE)。
- 示例素材说明见 [examples/README.md](examples/README.zh-CN.md)。

## 本版修改范围

本版专注于本机 ComfyUI 角色动画制作，包含三个技能：

| 技能 | 用途 |
|---|---|
| `comfyui-forge-generate2dmedia` | 本机 ComfyUI 图生视频、工作流检查与任务续接。 |
| `comfyui-forge-generate2dsprite` | 角色参考图片的检查、去背与输入准备。 |
| `comfyui-forge-video2dsprite` | 视频转透明动画、动作选帧、节奏调整与成品交付。 |

相较于上游，本版的主要调整包括：

- 视频生成统一使用本机 ComfyUI，移除云端 API、API key 配置与 CLI 生成后备路由。
- 使用独立技能名称、目录与安装记录，支持与原版并存。
- 提供用户工作流的节点映射、配置路径解析，以及生成任务续接与结果校验。
- 加入规格规划、帧数对齐与项目偏好保存，按用户语言确认规格与说明结果。
- 加入动作首图评估、构图留白、统一角色比例、位移处理、动作验收与重试决策。
- 依完整动作选帧、调整播放节奏并保留重要姿势，在最终成品尺寸下检查预览与验收。
- 标准交付为透明 PNG 帧、透明 PNG 图集、GIF 预览及源 MP4，整理为 ZIP。
- 提供离线测试，以及繁体中文、简体中文、英文、日文、韩文的 README、安装、工作流配置、使用、修改与示例说明。

本版不包含上游的地图、代码绘图、独立静态图集／图标处理及额外引擎传输与 runtime 功能，也未配置静态图片生成。工作流与模型由用户自行准备。

ComfyUI、Python 软件包、FFmpeg、模型、第三方节点，以及用户另外提供或生成的内容，依各自适用的许可处理。
