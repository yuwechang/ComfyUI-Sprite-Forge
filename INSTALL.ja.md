# Codex 向けインストール手順

[繁體中文](INSTALL.md) | [简体中文](INSTALL.zh-CN.md) | [English](INSTALL.en.md) | **日本語** | [한국어](INSTALL.ko.md)

## 前提条件

- Python 3.10+、FFmpeg、FFprobe。正常に実行できるか確認し、不足しているもののインストールを支援します。
- H3 ワークフローを実行できるローカル ComfyUI と、ユーザー自身の API 形式のワークフロー JSON。未提供の場合はファイルの場所を確認します。

ワークフローの API JSON は同梱していません。インストール前に [AGENTS.md](AGENTS.md) を読んでください。

## 1. プロジェクトと Python 環境の準備

プロジェクト全体を永続的なフォルダーに clone／ダウンロードします。以下の Windows PowerShell コマンドはプロジェクトのルートで実行し、`python` には Python 3.10+ を使用します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

以降のコマンドにはこの仮想環境の Python を使用します。他のプラットフォームでは `.venv/bin/python` です。インストール後もプロジェクトと `.venv` を保持してください。

## 2. ComfyUI の設定

初回は `local-comfyui/config.example.json` を `local-comfyui/config.local.json` にコピーします。既存の設定がある場合は確認して再利用します。

[docs/WORKFLOW.md](docs/WORKFLOW.ja.md) に従い、ユーザーの API JSON からサービスのアドレス、ワークフローのパス、ノードの対応、フレーム規則を設定します。パスは絶対パス、または設定ファイルのフォルダーからの相対パスです。ワークフローの変更が必要な場合は別のコピーに保存します。

## 3. 3 つのスキルをインストール

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --apply --host codex --config local-comfyui/config.local.json
```

このコマンドは以下のスキルをすべてインストールし、プロジェクトと設定のパスを記録します。

- `comfyui-forge-generate2dmedia`
- `comfyui-forge-generate2dsprite`
- `comfyui-forge-video2dsprite`

インストール先は `$CODEX_HOME/skills`、`CODEX_HOME` が未設定の場合は `$HOME/.codex/skills` です。

## 4. インストールの検証

インストール済みファイルを確認し、オフラインテストを実行します。

```powershell
.\.venv\Scripts\python.exe tools/comfyui_forge_install_skills.py --check --host codex
.\.venv\Scripts\python.exe tools/comfyui_forge_test_release.py
```

インストール先から ComfyUI の設定と接続を確認します。

```powershell
$SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py" --check
.\.venv\Scripts\python.exe "$SkillsRoot/comfyui-forge-video2dsprite/scripts/comfyui_forge_video2dsprite.py" doctor
```

ユーザーからワークフローのサイズ制約に合う画像とプロンプトが提供されている場合は、[docs/WORKFLOW.md](docs/WORKFLOW.ja.md) に従い、インストール先から `--dry-run` を実行して生成リクエストを検証します。

これらの確認では動画を生成しません。実際の生成テストはユーザーが別途依頼した場合に行います。

## 5. 結果の報告

プロジェクト、Python、スキル、設定のパスと、各確認の結果、未完了の項目を報告します。スキルを読み込むため、新しい Codex チャットを開くよう案内します。

## 更新と移動

プロジェクトの更新後はインストールと検証を再実行します。インストーラーは本プロジェクトの既存スキルをバックアップします。プロジェクトやワークフローを移動した場合は設定のパスを修正し、再インストールします。
