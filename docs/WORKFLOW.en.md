# Local H3 workflow configuration

[繁體中文](WORKFLOW.md) | [简体中文](WORKFLOW.zh-CN.md) | **English** | [日本語](WORKFLOW.ja.md) | [한국어](WORKFLOW.ko.md)

## Workflow format

Use an **Export (API) JSON** that already runs in local ComfyUI. Top-level keys are string node IDs, with `class_type` and `inputs` in each node. The canvas format with top-level `nodes` and `links` is unsupported.

The adapter uploads a first image and optional last image, writes the configured node inputs, submits through `/prompt`, polls `/history/{prompt_id}`, and downloads the MP4 through `/view`.

## Configuration fields

Create `local-comfyui/config.local.json` from [config.example.json](../local-comfyui/config.example.json), filling in values from the actual workflow.

Node bindings use `["node ID", "input name"]`, with string node IDs.

| Field | Configuration |
|---|---|
| `url` | Local ComfyUI address: HTTP on `127.0.0.1`, `localhost`, or `[::1]`, with a custom port if needed. Credentials, proxies, and redirects are unsupported. |
| `workflow` | Path to the user's API JSON. Relative paths resolve from the configuration directory. Use `/` or JSON-escaped `\\` for Windows paths. |
| `output_node` | ID of the node that outputs the MP4. |
| `bindings.image` | The first-image LoadImage `image` input; replaced with the filename returned by ComfyUI after upload. |
| `bindings.prompt` | Text input for the prompt. |
| `bindings.width / bindings.height` | Inputs controlling generation width and height; numeric values replace any existing connections at these inputs. |
| `bindings.length` | Input receiving the integer total frame count. |
| `bindings.fps` | Optional fps input on the video output node. If omitted, the workflow must use a fixed 24 fps. |
| `bindings.last_image` | Optional last-image LoadImage `image` input, paired with `last_frame_input`. |
| `last_frame_input` | Node and input consuming the last image. The adapter removes this connection when no last image is supplied. Omit this field and `bindings.last_image` if unsupported. |
| `bindings.seed` | Optional seed node and input. If omitted, the output branch is searched for `seed` / `noise_seed`, including upstream connections. |
| `fps / frame_multiple / frame_offset / frame_minimum` | Fixed at `24`, `17`, `5`, `5`, respectively; these are also the defaults when omitted. |
| `planning.minimum_source_size` | Optional verified minimum workflow input size `[width, height]`, checked by the specification planner. |
| `planning.dimension_multiple` | Optional size-alignment multiple for the planner, default `32`. Input images must still meet the adapter's multiple-of-32 requirement. |

## Frame and size limits

Source video uses a fixed 24 fps. Requested duration `a` must be greater than 0 and at most 15 seconds. Total frames are calculated below; `round` uses Python's nearest-integer rounding with ties to even:

```text
n = max(5, round(a * 24))
frames = min(345, n + (5 - n % 17) % 17)
```

Total frames follow `17k + 5`, capped at 345 frames and an actual duration of 14.375 seconds. `bindings.length` receives this count directly.

Input width and height must be multiples of 32 and meet the workflow's minimum size. Prepare `registration_job` again if a registered input image changes size.

## Output compatibility

The adapter submits only `output_node` and its upstream dependencies. The configured output node's history result must provide a `.mp4` item with `filename`, `subfolder`, and `type` in a `gifs`, `videos`, or `images` list. The adapter downloads the first matching MP4.

If a node only accepts seconds, or its output format or history structure differs, adjust a workflow copy or the adapter and verify again.

Each new generation writes the same nonnegative random integer seed to the detected seed inputs; workflows with no seed fields skip this step. Special seed ranges or multiple independent seeds require separate configuration. Resumed jobs retain the submitted workflow and seed.

## Verify configuration

Run tools with the project's `.venv` Python. `scripts` refers to the folder under the actual installed `comfyui-forge-generate2dmedia` directory:

```text
<Python> <scripts>/comfyui_forge_media.py --check
<Python> <scripts>/comfyui_forge_route_media.py video --route comfyui --reference <input-image> --prompt-file <prompt-text-file> --duration <requested-seconds> --out-dir <working-directory> --dry-run
```

`--check` connects to the local API and checks node classes in the execution branch and some known model-field options. `--dry-run` validates the request without connecting or creating an output directory. Neither generates video or verifies visual quality.

For installation and configuration-path updates, see [INSTALL.md](../INSTALL.en.md).
