# Supplied master stills

`scripts/comfyui_forge_master_still.py` prepares prompts and processes supplied images locally.
It has no image-generation provider, candidate generation or fallback.

- `prompt --spec SPEC.json --output-dir NEW` writes prompt.txt, spec.json and run.json.
- `edit-prompt --still IMAGE --spec SPEC.json --change TEXT --output-dir NEW` writes an edit prompt and references; it does not generate or edit pixels.
- `pad --input IMAGE --output-dir NEW` keys and fits an image to the class framing.
- `approve --still IMAGE --spec SPEC.json --output-dir NEW` writes master.png, master_rgba.png and master.json for animation.

Inspect the actual supplied image, silhouette, matte and framing before approval.
The optional provenance label records the source; it never selects a provider.
Run each command with --help for framing and reference options.
Character animation uses the sibling video2dsprite skill and local ComfyUI.
