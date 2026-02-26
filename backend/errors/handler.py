# 에러 핸들러 모듈
# 예외를 잡아 아키텍처 문서 4.3절의 stderr JSON 프로토콜로 출력한다
from __future__ import annotations

import json
import sys
from datetime import datetime

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import OcrModuleError


def _now_iso() -> str:
    """현재 시각을 ISO 8601 형식으로 반환한다."""
    return datetime.now().isoformat(timespec="seconds")


def _write_stderr(payload: dict[str, object]) -> None:
    """딕셔너리를 JSON 한 줄로 stderr에 출력한다."""
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


class ErrorHandler:
    """예외를 stderr JSON 메시지로 변환하여 출력하는 핸들러다."""

    @staticmethod
    def handle_fatal(exc: Exception) -> None:
        """복구 불가능한 치명적 에러를 stderr에 출력한다."""
        if isinstance(exc, OcrModuleError):
            payload: dict[str, object] = {
                "type": "error",
                "code": exc.code,
                "message": exc.message,
                "details": exc.detail or str(exc),
                "recoverable": exc.recoverable,
                "timestamp": _now_iso(),
            }
        else:
            # 알 수 없는 예외는 E050 시스템 에러로 매핑한다
            payload = {
                "type": "error",
                "code": ErrorCodes.SYSTEM_MISSING_DEPS,
                "message": ErrorCodes.get_message(ErrorCodes.SYSTEM_MISSING_DEPS),
                "details": f"{type(exc).__name__}: {exc}",
                "recoverable": False,
                "timestamp": _now_iso(),
            }
        _write_stderr(payload)

    @staticmethod
    def handle_page_error(page_num: int, exc: Exception) -> None:
        """개별 페이지 처리 실패를 stderr에 출력한다. 처리는 계속된다."""
        if isinstance(exc, OcrModuleError):
            code = exc.code
            message = exc.message
            detail = exc.detail or str(exc)
        else:
            # 페이지 레벨 미분류 예외는 E020으로 처리한다
            code = ErrorCodes.OCR_PAGE_FAILED
            message = ErrorCodes.get_message(ErrorCodes.OCR_PAGE_FAILED)
            detail = f"{type(exc).__name__}: {exc}"

        payload: dict[str, object] = {
            "type": "page_error",
            "page": page_num + 1,   # 사용자에게는 1-based 번호를 표시한다
            "code": code,
            "message": message,
            "details": detail,
            "recoverable": True,
            "timestamp": _now_iso(),
        }
        _write_stderr(payload)

    @staticmethod
    def handle_memory_warning(current_mb: float, threshold_mb: int) -> None:
        """메모리 경고 수준 도달 시 stdout에 로그로 출력한다.

        메모리 경고는 페이지 스킵이 아닌 단순 경고이므로
        error가 아닌 log 타입으로 전송한다.
        """
        payload: dict[str, object] = {
            "type": "log",
            "level": "warn",
            "message": f"메모리 사용량 경고: {current_mb:.0f}MB / 임계값 {threshold_mb}MB",
            "timestamp": _now_iso(),
        }
        # 로그는 stdout으로 출력한다 (Flutter가 error로 오인하지 않도록)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
