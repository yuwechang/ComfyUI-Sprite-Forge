# ComfyUI-Sprite-Forge repository instructions

This is an unofficial fork of https://github.com/0x0funky/agent-sprite-forge by 0x0funky. Preserve LICENSE and NOTICE.md. Do not imply upstream, ComfyUI or model-author endorsement.

For an explicit user request to install this repository, follow INSTALL.md. Preserve the whole repository and install ALL five comfyui-forge-* sibling skills with tools/install_skills.py. Never install just SKILL.md. Do not modify original Sprite Forge directories, manifests, credentials or environment variables. Do not treat a user request to prepare release files as permission to install into the user's real skills directory.

The sole generation provider is local ComfyUI. Still-image generation is not configured. Never add cloud/API-key/CLI fallback. User-supplied files and offline processing remain supported.

The user's ComfyUI must already run their H3 workflow. Read docs/WORKFLOW.md to bind their own Export (API) JSON. Ask for its path when missing. Do not download models, modify ComfyUI, install custom nodes or send GPU jobs merely to validate installation. --check is read-only; --dry-run does not submit.

Pending jobs are resumed, unknown jobs require queue/history inspection, completed artifacts are checksum-verified. Never re-submit a job just because polling or transport failed.

Run python tools/test_release.py for the supported offline release suite. Use a writable workspace TEMP/TMP if the OS temporary directory is blocked. Validate coexistence against isolated destinations, not another person's real installation.

Keep private local settings, workflows, generated media, keys, virtual environments and backups out of Git. Do not commit another person's path or replace repository placeholders with an invented GitHub URL. Retain this AGENTS.md in Git so an installing Codex can discover the protocol.
