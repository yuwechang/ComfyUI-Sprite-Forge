# Codex installation guide

[繁體中文](INSTALL.md) | [简体中文](INSTALL.zh-CN.md) | **English** | [日本語](INSTALL.ja.md) | [한국어](INSTALL.ko.md)

## Prerequisites

- Python 3.10+, FFmpeg, and FFprobe; check that they run and help install any missing tools.
- Local ComfyUI already able to run an H3 workflow, and the user's own API-format workflow JSON; ask for its location if it has not been supplied.

No workflow API JSON is bundled. Read [AGENTS.md](AGENTS.md) before installation.

## 1. Prepare the project and Python environment

Clone or download the complete project to a permanent directory. Run the following Windows PowerShell commands from the project root, using Python 3.10+ for `python`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use this virtual environment's Python for subsequent commands; on other platforms the path is `.venv/bin/python`. Keep the project and `.venv` after installation.

## 2. Configure ComfyUI

For first-time setup, copy `local-comfyui/config.example.json` to `local-comfyui/config.local.json`; check and reuse an existing configuration.

Follow [docs/WORKFLOW.md](docs/WORKFLOW.en.md) to map the service address, workflow path, node inputs, and frame rules using the user's API JSON. The workflow path may be absolute or relative to the configuration directory. Save a separate copy if the workflow needs changes.

## 3. Install the three skills

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --apply --host codex --config local-comfyui/config.local.json
```

This command installs all three skills and records the project and configuration paths:

- `comfyui-forge-generate2dmedia`
- `comfyui-forge-generate2dsprite`
- `comfyui-forge-video2dsprite`

The destination is `$CODEX_HOME/skills`, or `$HOME/.codex/skills` when `CODEX_HOME` is unset.

## 4. Verify the installation

Check installed files and run the offline tests:

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --check --host codex
.\.venv\Scripts\python.exe tools/comfyui_forge_test_release.py
```

Check the ComfyUI configuration and connection from the installed location:

```powershell
$SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py" --check
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-video2dsprite/scripts/comfyui_forge_video2dsprite.py" doctor
```

If the user supplies an image meeting the workflow's size requirements and a prompt, follow [docs/WORKFLOW.md](docs/WORKFLOW.en.md) to run `--dry-run` from the installed location and validate the generation request.

These checks do not generate video. An actual generation test requires a separate user request.

## 5. Report results

Report the project, Python, skills, and configuration paths, each check's result, and any incomplete steps. Remind the user to open a new Codex chat to load the skills.

## Updates and relocation

After updating the project, rerun installation and verification; the installer backs up this project's existing skills. If the project or workflow moves, correct the configuration paths and reinstall.
