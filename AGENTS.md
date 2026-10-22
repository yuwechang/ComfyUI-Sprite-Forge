# ComfyUI-Sprite-Forge repository instructions

This is an unofficial fork of https://github.com/0x0funky/agent-sprite-forge by 0x0funky. Preserve LICENSE and NOTICE.md. Do not imply upstream, ComfyUI or model-author endorsement.

For an explicit user request to install this repository, follow INSTALL.md. Preserve the whole repository and install the three animation-core comfyui-forge-* skills with tools/comfyui_forge_install_skills.py. The repository contains the three animation-core skills and their supporting tools.

Generation uses local ComfyUI; supplied images and videos also support offline processing. For action-reference assessment and optional preparation of an approved action still, follow skills/comfyui-forge-video2dsprite/SKILL.md.

The user's ComfyUI must already run their H3 workflow. Read docs/WORKFLOW.md to bind their own Export (API) JSON. Ask for its path when missing. Do not download models, modify ComfyUI, install custom nodes or send GPU jobs merely to validate installation. --check is read-only; --dry-run does not submit.

Pending jobs are resumed, unknown jobs require queue/history inspection, completed artifacts are checksum-verified. Never re-submit a job just because polling or transport failed.

Run python tools/comfyui_forge_test_release.py for the supported offline release suite. Use a writable workspace TEMP/TMP if the OS temporary directory is blocked. Validate coexistence against isolated destinations.

Keep private local settings, workflows, generated media, keys, virtual environments and backups out of Git.

Before animation generation, follow skills/comfyui-forge-video2dsprite/references/specification-guide.md: localized first-use/reuse confirmation, deterministic source recommendations and cadence, user-confirmed project-local preferences, and clean standard ZIP delivery.
