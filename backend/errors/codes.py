# 에러 코드 상수 모듈
# 아키텍처 문서 4.4절에 정의된 에러 코드 체계를 구현한다
from __future__ import annotations


class ErrorCodes:
    """에러 코드와 기본 메시지를 묶어 관리하는 상수 클래스다."""

    # PDF 입력 관련 에러 (E001~E003)
    PDF_CANNOT_OPEN: str = "E001"
    PDF_NOT_FOUND: str = "E002"
    PDF_NO_CONTENT: str = "E003"

    # 모델 관련 에러 (E010~E013)
    MODEL_DOWNLOAD_FAILED: str = "E010"
    MODEL_CORRUPTED: str = "E011"
    MODEL_LOAD_FAILED: str = "E012"
    MODEL_INCOMPATIBLE: str = "E013"

    # OCR 처리 에러 (E020~E021)
    OCR_PAGE_FAILED: str = "E020"
    OCR_TIMEOUT: str = "E021"

    # 출력 관련 에러 (E030~E031)
    OUTPUT_WRITE_FAILED: str = "E030"
    OUTPUT_DISK_FULL: str = "E031"

    # 메모리 관련 에러 (E040~E041)
    MEMORY_WARNING: str = "E040"
    MEMORY_FATAL: str = "E041"

    # 시스템 에러 (E050~E051)
    SYSTEM_MISSING_DEPS: str = "E050"
    SYSTEM_UNSUPPORTED: str = "E051"

    # PDF 분할 관련 에러 (E060~E061)
    SPLIT_INVALID_PARTS: str = "E060"
    SPLIT_FAILED: str = "E061"

    # 각 에러 코드에 대응하는 한국어 기본 메시지 매핑
    _MESSAGES: dict[str, str] = {
        "E001": "PDF 파일을 열 수 없음 — 파일이 손상되었거나 암호화되어 있음",
        "E002": "PDF 파일이 존재하지 않음",
        "E003": "PDF에 처리할 콘텐츠가 없음",
        "E010": "모델 다운로드 실패 — 네트워크 연결을 확인하세요",
        "E011": "모델 파일이 손상됨 — 재다운로드가 필요함",
        "E012": "모델 로드 실패 — 메모리가 부족함",
        "E013": "MLX 프레임워크가 설치되지 않았거나 호환되지 않음",
        "E020": "페이지 OCR 실패 — 해당 페이지를 건너뜀",
        "E021": "OCR 추론 타임아웃 — 해당 페이지를 건너뜀",
        "E030": "출력 PDF 생성 실패",
        "E031": "디스크 공간이 부족함",
        "E040": "메모리 사용량이 경고 수준을 초과함",
        "E041": "메모리 사용량이 한계를 초과하여 처리를 중단함",
        "E050": "필수 Python 패키지가 설치되지 않음",
        "E051": "지원하지 않는 플랫폼 — Apple Silicon macOS가 필요함",
        "E060": "PDF 분할 권 수가 유효하지 않음 — 1 이상, 총 페이지 수 이하여야 함",
        "E061": "PDF 분할 중 오류가 발생함",
    }

    @classmethod
    def get_message(cls, code: str) -> str:
        """에러 코드에 해당하는 한국어 메시지를 반환한다."""
        return cls._MESSAGES.get(code, f"알 수 없는 에러 ({code})")

    @classmethod
    def is_recoverable(cls, code: str) -> bool:
        """에러가 복구 가능한지(계속 처리 가능한지) 여부를 반환한다."""
        # 개별 페이지 실패 및 경고 수준 메모리는 복구 가능하다
        recoverable_codes: set[str] = {"E010", "E020", "E021", "E040"}
        return code in recoverable_codes
