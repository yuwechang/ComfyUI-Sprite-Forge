# 로컬 ComfyUI 설정 파일

[繁體中文](README.md) | [简体中文](README.zh-CN.md) | [English](README.en.md) | [日本語](README.ja.md) | **한국어**

이 폴더는 설정 템플릿을 제공합니다. ComfyUI, 모델 및 워크플로는 사용자가 준비합니다.

- `config.example.json`: 연결과 노드 매핑 설정 형식입니다. 노드 ID는 자신의 API JSON에 맞추며 프레임 규칙은 프로젝트의 고정값을 사용합니다.
- `config.local.json`: 템플릿으로 만든 개인 설정이며 Git에서 제외됩니다.
- `workflow.local.json`: 선택적인 개인 워크플로 저장 위치이며 Git에서 제외됩니다. 설정에서 다른 위치를 지정할 수도 있습니다.

워크플로는 로컬 ComfyUI에서 영상을 생성할 수 있어야 합니다. 상대 워크플로 경로는 설정 파일 폴더 기준입니다. 자세한 내용은 [워크플로 설정](../docs/WORKFLOW.ko.md)을 참조하세요.
