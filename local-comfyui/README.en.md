# Local ComfyUI configuration files

[繁體中文](README.md) | [简体中文](README.zh-CN.md) | **English** | [日本語](README.ja.md) | [한국어](README.ko.md)

This directory provides a configuration template. Users supply ComfyUI, models, and their workflow.

- `config.example.json`: connection and node-binding configuration format. Adapt node IDs to your API JSON; frame rules use the project's fixed values.
- `config.local.json`: personal configuration created from the template, ignored by Git.
- `workflow.local.json`: optional personal workflow location, ignored by Git. Configuration can also point elsewhere.

The workflow must already generate video in local ComfyUI. Relative workflow paths resolve from the configuration directory. See [workflow configuration](../docs/WORKFLOW.en.md) for full instructions.
