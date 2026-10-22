# インストール手順

[繁體中文](INSTALL.md) | [简体中文](INSTALL.zh-CN.md) | [English](INSTALL.en.md) | **日本語** | [한국어](INSTALL.ko.md)

## 前提条件

- 正常に実行できる Python 3.10+、FFmpeg、FFprobe。
- 動画を生成する場合は、H3 ワークフローを実行できるローカル ComfyUI と、自分の API 形式のワークフロー JSON を用意してください。

ワークフローの API JSON は同梱していません。

## 1. プロジェクトと Python 環境の準備

プロジェクト全体を永続的なフォルダーに clone／ダウンロードします。以下の Windows PowerShell コマンドはプロジェクトのルートで実行し、`python` には Python 3.10+ を使用します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

以降のコマンドにはこの仮想環境の Python を使用します。他のプラットフォームでは `.venv/bin/python` です。インストール後もプロジェクトと `.venv` を保持してください。

## 2. ComfyUI の設定

初回は `local-comfyui/config.example.json` を `local-comfyui/config.local.json` にコピーします。既存の設定がある場合は確認して再利用します。

[docs/WORKFLOW.md](docs/WORKFLOW.ja.md) に従い、自分の API JSON からサービスのアドレス、ワークフローのパス、ノードの対応、フレーム規則を設定します。パスは絶対パス、または設定ファイルのフォルダーからの相対パスです。ワークフローの変更が必要な場合は別のコピーに保存します。

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

生成リクエストを検証する場合は、ワークフローのサイズ制約に合う画像とプロンプトを用意し、[docs/WORKFLOW.md](docs/WORKFLOW.ja.md) に従い、インストール先から `--dry-run` を実行して生成リクエストを検証します。

これらの確認では動画を生成しません。実際の生成結果を試す場合は、インストール後にアニメーションを依頼してください。

## 5. インストール後

インストールと接続の確認がすべて通ったら、新しい Codex チャットを開いてスキルを読み込みます。[使用ガイド](docs/USAGE.ja.md) に従い、キャラクター画像や既存の動画を渡して制作を始められます。

## 更新と移動

プロジェクトの更新後はインストールと検証を再実行します。インストーラーは本プロジェクトの既存スキルをバックアップします。プロジェクトやワークフローを移動した場合は設定のパスを修正し、再インストールします。
