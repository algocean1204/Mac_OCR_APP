# 커스텀 예외 클래스 모듈
# 아키텍처 문서 10.2절에 정의된 예외 계층 구조를 구현한다
from __future__ import annotations

from backend.errors.codes import ErrorCodes


class OcrModuleError(Exception):
    """OCR 모듈 기본 예외 클래스다. 모든 커스텀 예외의 부모다."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        detail: str | None = None,
        recoverable: bool | None = None,
    ) -> None:
        # 메시지가 없으면 에러 코드에 등록된 기본 메시지를 사용한다
        self.code: str = code
        self.message: str = message or ErrorCodes.get_message(code)
        self.detail: str | None = detail

        # recoverable이 명시되지 않으면 코드 기반으로 자동 결정한다
        if recoverable is not None:
            self.recoverable: bool = recoverable
        else:
            self.recoverable = ErrorCodes.is_recoverable(code)

        super().__init__(self.message)


class PdfInputError(OcrModuleError):
    """PDF 입력 관련 에러 (E001~E003)."""

    def __init__(self, code: str = ErrorCodes.PDF_CANNOT_OPEN, **kwargs: object) -> None:
        super().__init__(code=code, recoverable=False, **kwargs)  # type: ignore[arg-type]


class ModelError(OcrModuleError):
    """모델 관련 에러 (E010~E013)."""

    def __init__(self, code: str = ErrorCodes.MODEL_LOAD_FAILED, **kwargs: object) -> None:
        super().__init__(code=code, **kwargs)  # type: ignore[arg-type]


class OcrProcessingError(OcrModuleError):
    """OCR 처리 에러 (E020~E021) — 기본적으로 복구 가능하다."""

    def __init__(self, code: str = ErrorCodes.OCR_PAGE_FAILED, **kwargs: object) -> None:
        super().__init__(code=code, recoverable=True, **kwargs)  # type: ignore[arg-type]


class OutputError(OcrModuleError):
    """출력 관련 에러 (E030~E031)."""

    def __init__(self, code: str = ErrorCodes.OUTPUT_WRITE_FAILED, **kwargs: object) -> None:
        super().__init__(code=code, recoverable=False, **kwargs)  # type: ignore[arg-type]


class MemoryLimitError(OcrModuleError):
    """메모리 한계 초과 에러 (E040~E041)."""

    def __init__(self, code: str = ErrorCodes.MEMORY_FATAL, **kwargs: object) -> None:
        super().__init__(code=code, **kwargs)  # type: ignore[arg-type]


class SplitError(OcrModuleError):
    """PDF 분할 관련 에러 (E060~E061)."""

    def __init__(self, code: str = ErrorCodes.SPLIT_FAILED, **kwargs: object) -> None:
        super().__init__(code=code, recoverable=False, **kwargs)  # type: ignore[arg-type]
