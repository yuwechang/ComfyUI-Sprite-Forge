# 설치 안내

[繁體中文](INSTALL.md) | [简体中文](INSTALL.zh-CN.md) | [English](INSTALL.en.md) | [日本語](INSTALL.ja.md) | **한국어**

## 설치 전제 조건

- 정상 실행되는 Python 3.10+, FFmpeg, FFprobe.
- 영상을 생성하려면 H3 워크플로를 실행할 수 있는 로컬 ComfyUI와 본인의 API 형식 워크플로 JSON을 준비하세요.

워크플로 API JSON은 포함되어 있지 않습니다.

## 1. 프로젝트와 Python 환경 준비

전체 프로젝트를 영구 폴더에 clone하거나 다운로드합니다. 아래 Windows PowerShell 명령은 프로젝트 루트에서 실행하며, `python`은 Python 3.10+여야 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

이후 명령에는 이 가상 환경의 Python을 사용합니다. 다른 플랫폼의 경로는 `.venv/bin/python`입니다. 설치 후에도 프로젝트와 `.venv`를 보관합니다.

## 2. ComfyUI 설정

처음 설정할 때 `local-comfyui/config.example.json`을 `local-comfyui/config.local.json`으로 복사합니다. 기존 설정은 확인한 뒤 재사용합니다.

[docs/WORKFLOW.md](docs/WORKFLOW.ko.md)에 따라 본인의 API JSON으로 서비스 주소, 워크플로 경로, 노드 연결 및 프레임 규칙을 설정합니다. 워크플로 경로는 절대 경로 또는 설정 파일 폴더 기준 상대 경로입니다. 워크플로를 수정해야 한다면 별도 사본으로 저장합니다.

## 3. 세 가지 스킬 설치

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --apply --host codex --config local-comfyui/config.local.json
```

이 명령은 아래 스킬을 모두 설치하고 프로젝트와 설정 경로를 기록합니다.

- `comfyui-forge-generate2dmedia`
- `comfyui-forge-generate2dsprite`
- `comfyui-forge-video2dsprite`

설치 위치는 `$CODEX_HOME/skills`이며, `CODEX_HOME`이 설정되지 않았다면 `$HOME/.codex/skills`입니다.

## 4. 설치 검증

설치 파일을 확인하고 오프라인 테스트를 실행합니다.

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --check --host codex
.\.venv\Scripts\python.exe tools/comfyui_forge_test_release.py
```

설치된 위치에서 ComfyUI 설정과 연결을 확인합니다.

```powershell
$SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py" --check
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-video2dsprite/scripts/comfyui_forge_video2dsprite.py" doctor
```

생성 요청을 검증하려면 워크플로 크기 조건에 맞는 이미지와 프롬프트를 준비하고 [docs/WORKFLOW.md](docs/WORKFLOW.ko.md)에 따라 설치된 위치에서 `--dry-run`을 실행하여 생성 요청을 검증합니다.

이 검사는 영상을 생성하지 않습니다. 실제 생성 결과를 시험하려면 설치 후 애니메이션을 요청하세요.

## 5. 설치 후

설치 및 연결 검사가 모두 통과하면 새 Codex 대화를 열어 스킬을 불러오세요. [사용 안내](docs/USAGE.ko.md)에 따라 캐릭터 이미지나 기존 영상을 제공해 제작을 시작할 수 있습니다.

## 업데이트 및 이동

프로젝트 업데이트 후 설치 명령과 검증을 다시 실행합니다. 설치 프로그램은 이 프로젝트의 기존 스킬을 백업합니다. 프로젝트나 워크플로를 옮겼다면 설정 경로를 수정하고 다시 설치합니다.
