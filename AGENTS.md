# ComfyUI-Sprite-Forge repository instructions

This is an unofficial fork of https://github.com/0x0funky/agent-sprite-forge by 0x0funky. Preserve LICENSE and NOTICE.md. Do not imply upstream, ComfyUI or model-author endorsement.

For an explicit user request to install this repository, follow INSTALL.md. Preserve the whole repository and install the three animation-core comfyui-forge-* skills with tools/comfyui_forge_install_skills.py. This fork contains only the three animation-core skills; retain only programs needed for local ComfyUI video-to-sprite and its reference preparation/standard delivery. Programs must come from this project or its installed copies, never another skill project. Never install just SKILL.md. Do not modify original Sprite Forge directories, manifests, credentials or environment variables. Do not treat a user request to prepare release files as permission to install into the user's real skills directory.

The sole generation provider is local ComfyUI. Still-image generation is not configured. Never add cloud/API-key/CLI fallback. User-supplied files and offline processing remain supported. Before animation, assess whether the reference fits the requested action as described in skills/comfyui-forge-video2dsprite/SKILL.md. An optional action still prepared separately with an available, user-authorized image tool is an input asset, not a provider fallback; preserve local-only preferences and obtain approval of the new still before video submission. Do not require a sketch or assume a particular image product is available.

The user's ComfyUI must already run their H3 workflow. Read docs/WORKFLOW.md to bind their own Export (API) JSON. Ask for its path when missing. Do not download models, modify ComfyUI, install custom nodes or send GPU jobs merely to validate installation. --check is read-only; --dry-run does not submit.

Pending jobs are resumed, unknown jobs require queue/history inspection, completed artifacts are checksum-verified. Never re-submit a job just because polling or transport failed.

Run python tools/comfyui_forge_test_release.py for the supported offline release suite. Use a writable workspace TEMP/TMP if the OS temporary directory is blocked. Validate coexistence against isolated destinations, not another person's real installation.

Keep private local settings, workflows, generated media, keys, virtual environments and backups out of Git. Do not commit another person's path or replace repository placeholders with an invented GitHub URL. Retain this AGENTS.md in Git so an installing Codex can discover the protocol.

Before animation generation, follow skills/comfyui-forge-video2dsprite/references/specification-guide.md: localized first-use/reuse confirmation, deterministic source recommendations and cadence, user-confirmed project-local preferences, and clean standard ZIP delivery. Do not silently reuse the author's prior settings or treat a saved specification as permission to submit a new job.
