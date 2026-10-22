# 安装说明

[繁體中文](INSTALL.md) | **简体中文** | [English](INSTALL.en.md) | [日本語](INSTALL.ja.md) | [한국어](INSTALL.ko.md)

## 安装前提

- 可正常运行的 Python 3.10+、FFmpeg 和 FFprobe。
- 需要生成视频时，请准备已能运行 H3 工作流的本机 ComfyUI，以及自己的 API 格式工作流 JSON。

本项目不附工作流 API JSON。

## 1. 准备项目与 Python 环境

将完整项目 clone／下载到永久文件夹。以下 Windows PowerShell 命令均在项目根目录执行，`python` 须为 Python 3.10+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

后续使用此虚拟环境的 Python；其他平台路径为 `.venv/bin/python`。安装后仍需保留项目和 `.venv`。

## 2. 创建 ComfyUI 配置

首次配置时，复制 `local-comfyui/config.example.json` 为 `local-comfyui/config.local.json`；已有配置则沿用并检查。

依照 [docs/WORKFLOW.md](docs/WORKFLOW.zh-CN.md)，使用你的 API JSON 设置服务地址、工作流路径、节点映射与帧数规则。工作流路径可为绝对路径，或相对于配置文件所在文件夹；需要调整工作流时另存副本。

## 3. 安装三个技能

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --apply --host codex --config local-comfyui/config.local.json
```

此命令完整安装以下技能，并记录项目及配置路径：

- `comfyui-forge-generate2dmedia`
- `comfyui-forge-generate2dsprite`
- `comfyui-forge-video2dsprite`

安装位置为 `$CODEX_HOME/skills`；未设置 `CODEX_HOME` 时为 `$HOME/.codex/skills`。

## 4. 验证安装

检查安装文件并运行离线测试：

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --check --host codex
.\.venv\Scripts\python.exe tools/comfyui_forge_test_release.py
```

从已安装位置检查 ComfyUI 配置与连接：

```powershell
$SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py" --check
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-video2dsprite/scripts/comfyui_forge_video2dsprite.py" doctor
```

如需检查生成请求，请准备符合工作流尺寸限制的图片与提示词，依照 [docs/WORKFLOW.md](docs/WORKFLOW.zh-CN.md) 从已安装位置运行 `--dry-run`。

以上检查不生成视频。如需测试实际生成效果，可在安装完成后提出动画需求。

## 5. 安装完成后

确认上述安装与连接检查均通过后，开启新的 Codex 对话以加载技能。接着可依照 [使用说明](docs/USAGE.zh-CN.md)，提供角色图片或已有视频开始制作。

## 更新与迁移

更新项目后，重新运行安装命令与验证；安装程序会备份本项目已有技能。项目或工作流迁移后，修正配置路径并重新安装。
