# 파일 유틸리티 모듈
# 입력 파일 검증, 출력 경로 생성, 파일명 새니타이징을 담당한다
from __future__ import annotations

import re
from pathlib import Path

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import PdfInputError, OutputError


# PDF 파일 매직 바이트 — 모든 PDF 파일의 첫 4바이트는 %PDF이다
_PDF_MAGIC_BYTES: bytes = b"%PDF"

# 파일 크기 제한 — 과도하게 큰 PDF 방어 (5GB)
_MAX_FILE_SIZE_BYTES: int = 5 * 1024 * 1024 * 1024

# 파일명에서 제거할 특수문자 패턴
_UNSAFE_FILENAME_PATTERN: re.Pattern[str] = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_pdf_file(pdf_path: str) -> Path:
    """PDF 파일의 존재, 확장자, 매직 바이트, 크기를 검증하고 절대 경로를 반환한다.

    Args:
        pdf_path: 검증할 PDF 파일 경로

    Returns:
        검증된 절대 경로 Path 객체

    Raises:
        PdfInputError: 파일이 없거나 유효하지 않은 PDF인 경우
    """
    path = Path(pdf_path).expanduser().resolve()

    # 파일 존재 여부 확인
    if not path.exists() or not path.is_file():
        raise PdfInputError(
            code=ErrorCodes.PDF_NOT_FOUND,
            detail=str(path),
        )

    # 파일 크기 제한 확인
    file_size = path.stat().st_size
    if file_size > _MAX_FILE_SIZE_BYTES:
        raise PdfInputError(
            code=ErrorCodes.PDF_CANNOT_OPEN,
            message=f"파일 크기가 너무 큼: {file_size / 1024 / 1024 / 1024:.1f}GB",
            detail=str(path),
        )

    # 빈 파일 확인
    if file_size == 0:
        raise PdfInputError(
            code=ErrorCodes.PDF_NO_CONTENT,
            detail=str(path),
        )

    # PDF 매직 바이트 검증 — 실제 PDF인지 확인한다
    _verify_pdf_magic_bytes(path)

    return path


def _verify_pdf_magic_bytes(path: Path) -> None:
    """파일의 첫 4바이트가 PDF 매직 바이트인지 확인한다."""
    try:
        with open(path, "rb") as f:
            header = f.read(4)
    except OSError as exc:
        raise PdfInputError(
            code=ErrorCodes.PDF_CANNOT_OPEN,
            detail=f"파일 읽기 실패: {exc}",
        ) from exc

    if header != _PDF_MAGIC_BYTES:
        raise PdfInputError(
            code=ErrorCodes.PDF_CANNOT_OPEN,
            message="PDF 형식이 아닌 파일임 — 매직 바이트 불일치",
            detail=f"파일 헤더: {header!r}",
        )


def sanitize_filename(name: str) -> str:
    """파일명에서 OS 예약 문자와 제어 문자를 제거하여 안전한 파일명을 반환한다."""
    # 위험 문자를 언더스코어로 대체한다
    sanitized = _UNSAFE_FILENAME_PATTERN.sub("_", name)
    # 앞뒤 공백과 마침표를 제거한다
    sanitized = sanitized.strip(". ")
    # 빈 결과를 방어한다
    return sanitized or "output"


def generate_output_path(input_path: Path, output_dir: Path) -> Path:
    """입력 파일명을 기반으로 충돌 없는 출력 파일 경로를 생성한다.

    출력 규칙: {원본파일명}_OCR.pdf
    동명 파일이 있으면: {원본파일명}_OCR(2).pdf, _OCR(3).pdf ...

    Args:
        input_path: 원본 PDF 경로
        output_dir: 출력 파일 저장 디렉토리

    Returns:
        충돌 없는 출력 PDF 경로

    Raises:
        OutputError: 출력 디렉토리 생성 실패 시
    """
    _ensure_output_dir(output_dir)

    base_name = sanitize_filename(input_path.stem)
    candidate = output_dir / f"{base_name}_OCR.pdf"

    # 충돌 없는 경로를 찾을 때까지 번호를 증가시킨다
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{base_name}_OCR({counter}).pdf"
        counter += 1

    return candidate


def _ensure_output_dir(output_dir: Path) -> None:
    """출력 디렉토리가 없으면 생성한다."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(
            code=ErrorCodes.OUTPUT_WRITE_FAILED,
            message="출력 디렉토리를 생성할 수 없음",
            detail=f"{output_dir}: {exc}",
        ) from exc
