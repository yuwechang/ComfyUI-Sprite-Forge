# 원작자와 변경 사항

[繁體中文](NOTICE.md) | [简体中文](NOTICE.zh-CN.md) | [English](NOTICE.en.md) | [日本語](NOTICE.ja.md) | **한국어**

## 출처 및 라이선스

이 프로젝트는 [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge)를 기반으로 수정한 비공식 버전입니다.

- 원작자: 0x0funky, Copyright (c) 2026 0x0funky.
- 수정 및 예제 소재: yuwechang, Copyright (c) 2026 yuwechang.
- 소스 코드, 수정 사항 및 `examples/`의 캐릭터 원본 이미지, PNG 시트, GIF 애니메이션은 MIT 라이선스를 따릅니다. 전체 조건과 저작권 표시는 [LICENSE](LICENSE)를 참조하세요.
- 예제 소재 설명은 [examples/README.md](examples/README.ko.md)를 참조하세요.

## 이 버전의 변경 범위

이 버전은 로컬 ComfyUI를 통한 캐릭터 애니메이션 제작에 집중하며 세 가지 스킬을 포함합니다.

| 스킬 | 용도 |
|---|---|
| `comfyui-forge-generate2dmedia` | 로컬 ComfyUI 이미지 기반 영상 생성, 워크플로 검사 및 작업 재개. |
| `comfyui-forge-generate2dsprite` | 캐릭터 참조 이미지 검사, 배경 제거 및 입력 준비. |
| `comfyui-forge-video2dsprite` | 영상을 투명 애니메이션으로 변환, 프레임 선택, 타이밍 조정 및 결과물 제공. |

원본 대비 주요 변경 사항:

- 영상 생성을 로컬 ComfyUI로 통일하고 클라우드 API, API 키 설정 및 CLI 생성 대체 경로를 제거.
- 독립된 스킬 이름, 폴더 및 설치 기록으로 원본과 공존.
- 사용자 워크플로 노드 연결, 설정 경로 해석, 작업 재개 및 결과 검증.
- 규격 계획, 프레임 정렬 및 프로젝트 설정 저장. 사용자 언어로 확인 및 설명 제공.
- 동작 전용 시작 이미지 평가, 구도 여백, 일관된 캐릭터 크기, 이동 처리, 동작 검토 및 재시도 판단.
- 완전한 동작에서 프레임 선택, 재생 타이밍 조정, 주요 포즈 보존 및 최종 크기의 미리보기와 검수.
- 투명 PNG 프레임, 투명 PNG 시트, GIF 미리보기 및 원본 MP4를 표준 ZIP으로 제공.
- 오프라인 테스트와 번체 중국어, 간체 중국어, 영어, 일본어, 한국어의 README, 설치, 워크플로 설정, 사용법, 변경 사항 및 예제 안내.

원본의 맵 생성, 코드 기반 그림, 독립적인 정적 시트／아이콘 처리, 추가 엔진 전송 및 runtime 기능은 포함하지 않습니다. 정지 이미지 생성도 설정되어 있지 않습니다. 워크플로와 모델은 사용자가 준비합니다.

ComfyUI, Python 패키지, FFmpeg, 모델, 서드파티 노드 및 사용자가 별도로 제공하거나 생성한 콘텐츠에는 각각 해당 라이선스가 적용됩니다.
