# ローカル H3 ワークフローの設定

[繁體中文](WORKFLOW.md) | [简体中文](WORKFLOW.zh-CN.md) | [English](WORKFLOW.en.md) | **日本語** | [한국어](WORKFLOW.ko.md)

## ワークフローの形式

ローカル ComfyUI で実行できる **Export (API) JSON** を使用します。トップレベルのキーは文字列のノード ID で、各ノードに `class_type` と `inputs` を含めます。トップレベルに `nodes`、`links` を持つキャンバス形式は使用できません。

adapter は開始画像と任意の終了画像をアップロードし、設定に従ってノード入力を書き込み、`/prompt` で送信、`/history/{prompt_id}` で結果を確認し、`/view` から MP4 を取得します。

## 設定項目

[config.example.json](../local-comfyui/config.example.json) から `local-comfyui/config.local.json` を作成し、実際のワークフローに合わせて設定します。

ノードの対応は `["ノード ID", "input 名"]` で指定し、ID は文字列にします。

| 項目 | 設定内容 |
|---|---|
| `url` | ローカル ComfyUI のアドレス。HTTP の `127.0.0.1`、`localhost`、`[::1]` と任意のポートに対応します。認証情報、プロキシ、リダイレクトには対応しません。 |
| `workflow` | ユーザーの API JSON のパス。相対パスは設定ファイルのフォルダーが基準です。Windows では `/` または JSON でエスケープした `\\` を使用します。 |
| `output_node` | MP4 を出力するノードの ID。 |
| `bindings.image` | 開始画像を読み込む LoadImage の `image` input。アップロード後、ComfyUI が返すファイル名を書き込みます。 |
| `bindings.prompt` | プロンプトのテキスト input。 |
| `bindings.width / bindings.height` | 生成サイズを制御する幅と高さの input。既存の接続は数値で置き換えます。 |
| `bindings.length` | 整数の総フレーム数を受け取る input。 |
| `bindings.fps` | 任意。動画出力ノードの fps input。省略時はワークフローを 24 fps に固定します。 |
| `bindings.last_image` | 任意。終了画像を読み込む LoadImage の `image` input。`last_frame_input` と組み合わせます。 |
| `last_frame_input` | 終了画像を受け取るノードと input。画像未指定時はこの接続を削除します。終了画像機能がなければ、この項目と `bindings.last_image` を省略します。 |
| `bindings.seed` | 任意。シードのノードと input。省略時は出力分岐の `seed`／`noise_seed` とその上流接続を自動検出します。 |
| `fps / frame_multiple / frame_offset / frame_minimum` | それぞれ `24`、`17`、`5`、`5` に固定。省略時も同じ値です。 |
| `planning.minimum_source_size` | 任意。ワークフローで検証済みの最小入力サイズ `[幅, 高さ]`。仕様計算ツールで確認します。 |
| `planning.dimension_multiple` | 任意。仕様計算ツールのサイズ整列単位。初期値は `32`。入力画像には adapter の 32 の倍数制約も適用されます。 |

## フレームとサイズの制約

元動画は 24 fps 固定です。リクエスト時間 `a` は 0 より大きく、15 秒以下です。総フレーム数は次の式で計算し、`round` は Python の最近接整数への丸め（中間値は偶数）を使用します。

```text
n = max(5, round(a * 24))
frames = min(345, n + (5 - n % 17) % 17)
```

総フレーム数は `17k + 5` に従い、上限は 345 フレーム、実際の長さは最大 14.375 秒です。`bindings.length` はこの値を直接受け取ります。

入力画像の幅と高さは 32 の倍数で、ワークフローの最小サイズを満たす必要があります。登録済み画像のサイズを変えた場合は `registration_job` を再作成します。

## 出力の互換性

adapter が送信するのは `output_node` と上流の依存ノードのみです。指定出力ノードの history は、`gifs`、`videos`、`images` のいずれかのリストに、`filename`、`subfolder`、`type` を含む `.mp4` 項目を返す必要があります。最初に一致した MP4 を取得します。

秒数のみを受け取るノードや、出力形式・history 構造が異なる場合は、ワークフローのコピーまたは adapter を調整して再検証します。

新規生成ごとに、検出したシード入力へ同じ非負整数の乱数シードを書き込みます。シード項目がなければ省略します。特殊な範囲や複数の独立したシードは別途設定が必要です。再開するジョブでは送信済みのワークフローとシードを維持します。

## 設定の検証

プロジェクトの `.venv` の Python を使用します。`scripts` は実際のインストール先の `comfyui-forge-generate2dmedia` 内にあるフォルダーです。

```text
<Python> <scripts>/comfyui_forge_media.py --check
<Python> <scripts>/comfyui_forge_route_media.py video --route comfyui --reference <入力画像> --prompt-file <プロンプトのテキストファイル> --duration <リクエスト秒数> --out-dir <作業フォルダー> --dry-run
```

`--check` はローカル API に接続し、実行分岐のノードクラスと一部の既知モデル項目の選択肢を確認します。`--dry-run` は接続や出力フォルダーの作成をせずにリクエストを検証します。どちらも動画の生成や画質の検証は行いません。

インストールと設定パスの更新は [INSTALL.md](../INSTALL.ja.md) を参照してください。
