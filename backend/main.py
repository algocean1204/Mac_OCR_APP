# OCR 백엔드 엔트리포인트
# Flutter subprocess가 이 파일을 직접 실행한다
# stdout: NDJSON 진행률 메시지
# stderr: JSON 에러 메시지
from __future__ import annotations

import os
import sys

# HuggingFace/tqdm 진행률 바를 비활성화한다
# stdout/stderr에 NDJSON 이외의 텍스트가 섞이면 Flutter 파싱이 실패하므로
# 모든 서드파티 진행률 출력을 억제해야 한다
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def main() -> int:
    """파이프라인을 실행하고 종료 코드를 반환한다.

    Returns:
        0: 정상 종료
        1: 에러 종료
    """
    # 의존성 임포트를 main 함수 내에서 수행하여 임포트 에러를 포착한다
    try:
        from backend.config.settings import load_config
        from backend.errors.handler import ErrorHandler
        from backend.pipeline.controller import PipelineController
    except ImportError as exc:
        _emit_import_error(exc)
        return 1

    error_handler = ErrorHandler()

    try:
        # CLI 인자에서 설정을 로드한다
        config = load_config()
    except SystemExit as exc:
        # argparse 에러 (잘못된 인자) — argparse가 이미 메시지를 출력했다
        return int(exc.code) if exc.code is not None else 1
    except Exception as exc:
        error_handler.handle_fatal(exc)
        return 1

    try:
        # 파이프라인 실행
        controller = PipelineController(config)
        controller.run()
        return 0
    except KeyboardInterrupt:
        # 사용자가 Ctrl+C로 중단한 경우
        _emit_log("info", "사용자 중단 요청")
        return 0
    except Exception as exc:
        error_handler.handle_fatal(exc)
        return 1


def _emit_import_error(exc: ImportError) -> None:
    """임포트 에러를 stderr에 JSON 형식으로 출력한다."""
    import json
    from datetime import datetime

    payload = {
        "type": "error",
        "code": "E050",
        "message": "필수 Python 패키지가 설치되지 않음",
        "details": f"ImportError: {exc}",
        "recoverable": False,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def _emit_log(level: str, message: str) -> None:
    """stdout에 로그 메시지를 출력한다."""
    import json
    from datetime import datetime

    payload = {
        "type": "log",
        "level": level,
        "message": message,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.exit(main())
