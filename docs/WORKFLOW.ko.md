# 로컬 H3 워크플로 설정

[繁體中文](WORKFLOW.md) | [简体中文](WORKFLOW.zh-CN.md) | [English](WORKFLOW.en.md) | [日本語](WORKFLOW.ja.md) | **한국어**

## 워크플로 형식

로컬 ComfyUI에서 이미 실행되는 **Export (API) JSON**을 사용합니다. 최상위 키는 문자열 노드 ID이며 각 노드는 `class_type`과 `inputs`를 포함합니다. 최상위에 `nodes`, `links`가 있는 캔버스 형식은 지원하지 않습니다.

adapter는 시작 이미지와 선택적인 마지막 이미지를 업로드하고, 설정에 따라 노드 입력을 기록하며, `/prompt`로 제출하고 `/history/{prompt_id}`에서 결과를 확인한 뒤 `/view`로 MP4를 다운로드합니다.

## 설정 필드

[config.example.json](../local-comfyui/config.example.json)으로 `local-comfyui/config.local.json`을 만들고 실제 워크플로에 맞게 설정합니다.

노드 연결은 `["노드 ID", "input 이름"]`을 사용하며 ID는 문자열입니다.

| 필드 | 설정 기준 |
|---|---|
| `url` | 로컬 ComfyUI 주소입니다. HTTP의 `127.0.0.1`, `localhost`, `[::1]`과 사용자 지정 포트를 지원합니다. 인증 정보, 프록시, 리디렉션은 지원하지 않습니다. |
| `workflow` | 사용자의 API JSON 경로입니다. 상대 경로는 설정 파일 폴더 기준입니다. Windows 경로는 `/` 또는 JSON 이스케이프한 `\\`를 사용합니다. |
| `output_node` | MP4를 실제로 출력하는 노드 ID입니다. |
| `bindings.image` | 시작 이미지 LoadImage의 `image` input입니다. 업로드 후 ComfyUI가 반환한 파일명을 씁니다. |
| `bindings.prompt` | 프롬프트 텍스트 input입니다. |
| `bindings.width / bindings.height` | 생성 너비와 높이를 제어하는 input입니다. 해당 위치의 기존 연결은 숫자로 대체됩니다. |
| `bindings.length` | 정수 총 프레임 수를 받는 input입니다. |
| `bindings.fps` | 선택 사항인 영상 출력 노드의 fps input입니다. 생략하면 워크플로를 24 fps로 고정해야 합니다. |
| `bindings.last_image` | 선택 사항인 마지막 이미지 LoadImage의 `image` input입니다. `last_frame_input`과 함께 사용합니다. |
| `last_frame_input` | 마지막 이미지를 받는 노드와 input입니다. 마지막 이미지가 없으면 이 연결을 제거합니다. 기능이 없다면 이 필드와 `bindings.last_image`를 생략합니다. |
| `bindings.seed` | 선택 사항인 시드 노드와 input입니다. 생략하면 출력 분기의 `seed`／`noise_seed`와 상위 연결을 자동으로 찾습니다. |
| `fps / frame_multiple / frame_offset / frame_minimum` | 각각 `24`, `17`, `5`, `5`로 고정되며, 생략해도 이 값을 사용합니다. |
| `planning.minimum_source_size` | 선택 사항인 검증된 최소 워크플로 입력 크기 `[너비, 높이]`입니다. 규격 도구에서 확인합니다. |
| `planning.dimension_multiple` | 선택 사항인 규격 도구의 크기 정렬 배수이며 기본값은 `32`입니다. 입력 이미지는 adapter의 32 배수 제한도 충족해야 합니다. |

## 프레임 및 크기 제한

원본 영상은 24 fps로 고정됩니다. 요청 시간 `a`는 0보다 크고 15초 이하여야 합니다. 총 프레임 수는 아래와 같이 계산하며, `round`는 Python의 가장 가까운 정수 반올림을 사용합니다(정확히 중간이면 짝수).

```text
n = max(5, round(a * 24))
frames = min(345, n + (5 - n % 17) % 17)
```

총 프레임 수는 `17k + 5`를 따르며 최대 345프레임, 실제 길이는 최대 14.375초입니다. `bindings.length`는 이 값을 직접 받습니다.

입력 이미지 너비와 높이는 32의 배수이며 워크플로의 최소 크기를 충족해야 합니다. 등록된 입력 이미지의 크기가 바뀌면 `registration_job`을 다시 준비합니다.

## 출력 호환성

adapter는 `output_node`와 그 상위 종속 노드만 제출합니다. 지정된 출력 노드의 history 결과는 `gifs`, `videos`, `images` 중 한 목록에 `filename`, `subfolder`, `type`이 포함된 `.mp4` 항목을 제공해야 합니다. 첫 번째 일치하는 MP4를 다운로드합니다.

노드가 초 단위만 받거나 출력 형식 또는 history 구조가 다르다면 워크플로 사본이나 adapter를 수정한 후 다시 검증합니다.

새 생성 작업마다 감지된 시드 입력에 동일한 음이 아닌 정수 난수 시드를 기록합니다. 시드 필드가 없다면 건너뜁니다. 특수 시드 범위나 여러 독립 시드가 필요하면 별도로 설정해야 합니다. 재개된 작업은 제출된 워크플로와 시드를 유지합니다.

## 설정 검증

프로젝트 `.venv`의 Python으로 실행합니다. `scripts`는 실제 설치된 `comfyui-forge-generate2dmedia` 아래 폴더입니다.

```text
<Python> <scripts>/comfyui_forge_media.py --check
<Python> <scripts>/comfyui_forge_route_media.py video --route comfyui --reference <입력-이미지> --prompt-file <프롬프트-텍스트-파일> --duration <요청-초> --out-dir <작업-폴더> --dry-run
```

`--check`는 로컬 API에 연결하여 실행 분기의 노드 클래스와 일부 알려진 모델 필드 옵션을 확인합니다. `--dry-run`은 연결하거나 출력 폴더를 만들지 않고 요청을 검증합니다. 둘 다 영상을 생성하거나 실제 화질을 검증하지 않습니다.

설치 및 설정 경로 업데이트는 [INSTALL.md](../INSTALL.ko.md)를 참조하세요.
