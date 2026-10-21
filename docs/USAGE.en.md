# Usage and animation settings

[繁體中文](USAGE.md) | [简体中文](USAGE.zh-CN.md) | **English** | [日本語](USAGE.ja.md) | [한국어](USAGE.ko.md)

## Getting started

After installation, open a new Codex chat, attach a character image, and describe the action you want. For example:

> Use comfyui-forge-video2dsprite to make a right-facing run cycle in place from this character image, with a transparent animation and GIF preview.

You can specify direction, loop or single playback, final dimensions, and playback duration. You can also supply an existing video for conversion into a transparent character animation.

## Choosing settings

On first use, Codex confirms final dimensions and playback duration, defaulting to **128×128 and 1 second**. You can choose different settings.

Output starts at **8 fps**. Codex assesses **4–16 fps** for the action, balancing clarity and frame count. Rates above 16 fps require an explanation and your approval, up to 24 fps. You do not need to know which fps to choose.

Choose a source-video resolution based on computer performance and the detail you need, subject to workflow compatibility:

| Option | Resolution |
|---|---|
| 1. Performance | 512×512 |
| 2. Balanced (default) | 768×768 |
| 3. Quality | 1024×1024 |

Source-video resolution and duration differ from the final assets. Codex automatically plans a longer source and selects one complete action for the result. Before each generation, it shows the current final and source settings. Confirmed settings can be reused in the same chat.

## Production

Codex first assesses whether the character image suits the requested action. If an action-specific starting image is needed, it shows the new image for your approval. Local ComfyUI generates the video, followed by background removal, registration, frame selection, and playback review.

If two consecutive generations show the same mismatch, Codex explains the issue and lets you choose whether to adjust the condition or keep trying with the original requirement. Results still need review for character appearance, complete motion, and transparent edges.

## What you receive

The final ZIP contains:

- Selected transparent PNG frames.
- A transparent PNG animation sheet.
- A GIF preview.
- The original source MP4.

The chat also displays the preview, sheet, and source video, with final dimensions, frame count, fps, and playback mode. Read the sheet left to right, then top to bottom. Fewer than 8 frames use one row; 8 or more use two rows.

A GIF is a convenient preview and may repeat even for a one-shot action. Follow the delivery notes for loop or single playback in your game. GIF transparency and timing precision are limited; use PNG for the final transparent assets.

Intermediate files and review records remain in a separately linked working directory. If you later only need different frame selection or playback timing, ask Codex to reuse the existing video where possible.
