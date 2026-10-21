# ローカル ComfyUI の設定ファイル

[繁體中文](README.md) | [简体中文](README.zh-CN.md) | [English](README.en.md) | **日本語** | [한국어](README.ko.md)

このフォルダーには設定テンプレートがあります。ComfyUI、モデル、ワークフローはユーザーが用意します。

- `config.example.json`：接続とノード対応の設定形式。ノード ID は自身の API JSON に合わせ、フレーム規則はプロジェクトの固定値を使います。
- `config.local.json`：テンプレートから作る個人設定。Git の対象外です。
- `workflow.local.json`：任意の個人ワークフロー保存先。Git の対象外です。設定から別の場所を指定することもできます。

ワークフローはローカル ComfyUI で動画を生成できる必要があります。相対パスは設定ファイルのフォルダーが基準です。詳細は [ワークフロー設定](../docs/WORKFLOW.ja.md) を参照してください。
