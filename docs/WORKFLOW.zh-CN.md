# 本机 H3 工作流配置

[繁體中文](WORKFLOW.md) | **简体中文** | [English](WORKFLOW.en.md) | [日本語](WORKFLOW.ja.md) | [한국어](WORKFLOW.ko.md)

## 工作流格式

使用已能在本机 ComfyUI 运行的 **Export (API) JSON**。顶层以字符串节点 ID 为键，每个节点包含 `class_type` 与 `inputs`；含顶层 `nodes`、`links` 的画布格式不适用。

adapter 上传首图与可选尾图，依配置写入节点输入，通过 `/prompt` 提交、`/history/{prompt_id}` 查询结果，再由 `/view` 下载 MP4。

## 配置字段

使用 [config.example.json](../local-comfyui/config.example.json) 创建 `local-comfyui/config.local.json`，根据实际工作流填写以下字段。

所有节点映射使用 `["节点 ID", "input 名称"]`，节点 ID 为字符串。

| 字段 | 配置依据 |
|---|---|
| `url` | 本机 ComfyUI 地址，支持 HTTP 的 `127.0.0.1`、`localhost` 或 `[::1]` 及自定义端口；不支持登录凭据、proxy 或 redirect。 |
| `workflow` | 用户的 API JSON 路径；相对路径以配置文件所在文件夹解析。Windows 路径使用 `/` 或 JSON 转义的 `\\`。 |
| `output_node` | 实际输出 MP4 的节点 ID。 |
| `bindings.image` | 首图 LoadImage 的 `image` input；上传后写入 ComfyUI 返回的文件名。 |
| `bindings.prompt` | 提示词文本 input。 |
| `bindings.width / bindings.height` | 实际控制生成宽高的 input；指定位置原有的连接会被数值替换。 |
| `bindings.length` | 接收整数总帧数的 input。 |
| `bindings.fps` | 可选，视频输出节点的 fps input；省略时工作流须固定为 24 fps。 |
| `bindings.last_image` | 可选，尾图 LoadImage 的 `image` input，须搭配 `last_frame_input`。 |
| `last_frame_input` | 实际接收尾图的节点与 input；未提供尾图时 adapter 移除此处连接。无尾图功能时省略此字段与 `bindings.last_image`。 |
| `bindings.seed` | 可选，随机种子的节点与 input；省略时自动寻找输出分支的 `seed`／`noise_seed`，包括其上游连接。 |
| `fps / frame_multiple / frame_offset / frame_minimum` | 固定为 `24`、`17`、`5`、`5`；省略时采用这些值。 |
| `planning.minimum_source_size` | 可选，工作流已验证的最低输入尺寸 `[宽, 高]`，供规格工具检查。 |
| `planning.dimension_multiple` | 可选，规格工具的尺寸对齐倍数，默认 `32`；输入图片仍须符合 adapter 的 32 倍数限制。 |

## 帧数与尺寸限制

源视频固定 24 fps，请求时长 `a` 为大于 0、最多 15 秒的数值。总帧数计算如下，`round` 使用 Python 的最近整数、正中间取偶数规则：

```text
n = max(5, round(a * 24))
frames = min(345, n + (5 - n % 17) % 17)
```

总帧数符合 `17k + 5`，最多 345 帧，实际最长 14.375 秒。`bindings.length` 直接接收此数值。

输入图片宽高须为 32 的倍数，并符合工作流的最低尺寸。更改已登记输入图片的尺寸后，须重新准备 `registration_job`。

## 输出兼容性

adapter 只提交 `output_node` 及其上游依赖节点。指定输出节点的 history 结果须在 `gifs`、`videos` 或 `images` 列表中提供含 `filename`、`subfolder`、`type` 的 `.mp4` 项目；adapter 下载第一个符合的 MP4。

如果节点只接受秒数、输出格式或 history 结构不同，须调整工作流副本或 adapter 后再验证。

每个新生成任务会为找到的种子输入写入同一个非负整数随机种子；没有种子字段则跳过。特殊种子范围或多个独立种子需求须另行配置。续接任务沿用已提交的工作流与种子。

## 验证配置

使用项目 `.venv` 的 Python 执行工具，`scripts` 为 `comfyui-forge-generate2dmedia` 实际安装目录下的文件夹：

```text
<Python> <scripts>/comfyui_forge_media.py --check
<Python> <scripts>/comfyui_forge_route_media.py video --route comfyui --reference <输入图片> --prompt-file <提示词文本文件> --duration <请求秒数> --out-dir <工作目录> --dry-run
```

`--check` 连接本机 API，检查执行分支的节点类型与部分已知模型字段选项；`--dry-run` 检查请求，不连接、不创建输出目录。两者均不生成视频，也不验证实际画面质量。

安装及配置路径的更新方式见 [INSTALL.md](../INSTALL.zh-CN.md)。
