# PDF 분할 모듈
# OCR 완료된 마스터 PDF를 N권으로 분할한다
# chunk_size(기본 10) 단위로 정렬하여 분할한다
# PyMuPDF의 insert_pdf를 사용하여 메타데이터, 투명 텍스트 레이어, 북마크를 보존한다
from __future__ import annotations

from pathlib import Path

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import SplitError
from backend.progress.reporter import ProgressReporter


def split_pdf(
    source_path: Path,
    num_parts: int,
    reporter: ProgressReporter,
    chunk_size: int = 10,
) -> list[Path]:
    """완성된 마스터 PDF를 N권으로 분할한다.

    chunk_size 단위로 정렬하여 분할한다.
    예: 100페이지 / 4권 / chunk_size=10 → 30, 30, 20, 20

    Args:
        source_path: 분할할 원본 PDF 절대 경로
        num_parts: 분할 권 수 (1이면 복사만 수행)
        reporter: NDJSON 진행률 보고자
        chunk_size: 페이지 정렬 단위 (기본값: 10)

    Returns:
        생성된 분할 PDF 경로 목록 (권 순서대로)

    Raises:
        SplitError: num_parts가 유효하지 않거나 분할 중 오류 발생 시
    """
    import fitz

    # 원본 PDF를 열고 총 페이지 수를 확인한다
    try:
        doc = fitz.open(str(source_path))
    except Exception as exc:
        raise SplitError(
            code=ErrorCodes.SPLIT_FAILED,
            detail=f"원본 PDF 열기 실패: {exc}",
        ) from exc

    total_pages = len(doc)

    # 입력값 유효성 검사
    _validate_split_params(num_parts, total_pages, doc)

    # N=1인 경우 분할 없이 원본 경로를 반환한다
    if num_parts == 1:
        doc.close()
        return _handle_single_part(source_path, reporter)

    # 권별 페이지 범위를 chunk_size 단위로 정렬하여 계산한다
    page_ranges = _calculate_page_ranges(total_pages, num_parts, chunk_size)

    # 각 권을 순서대로 생성한다
    output_paths = _generate_parts(
        doc, page_ranges, source_path, num_parts, reporter
    )

    doc.close()

    # 분할 완료를 보고한다
    reporter.report_split_complete([str(p) for p in output_paths])

    return output_paths


def _validate_split_params(
    num_parts: int,
    total_pages: int,
    doc: object,
) -> None:
    """분할 권 수가 유효한지 검사한다."""
    import fitz

    if num_parts <= 0:
        if isinstance(doc, fitz.Document):
            doc.close()
        raise SplitError(
            code=ErrorCodes.SPLIT_INVALID_PARTS,
            detail=f"num_parts={num_parts} — 1 이상이어야 함",
        )

    if num_parts > total_pages:
        if isinstance(doc, fitz.Document):
            doc.close()
        raise SplitError(
            code=ErrorCodes.SPLIT_INVALID_PARTS,
            detail=(
                f"num_parts={num_parts}가 총 페이지 수({total_pages})를 초과함 "
                "— 권 수는 페이지 수 이하여야 함"
            ),
        )


def _calculate_page_ranges(
    total_pages: int,
    num_parts: int,
    chunk_size: int = 10,
) -> list[tuple[int, int]]:
    """각 권의 시작/끝 페이지 인덱스를 chunk_size 단위로 정렬하여 계산한다.

    예: 100페이지 / 4권 / chunk_size=10
    → base=20, extra=2, leftover=0
    → 30, 30, 20, 20

    Args:
        total_pages: 총 페이지 수
        num_parts: 분할 권 수
        chunk_size: 페이지 정렬 단위

    Returns:
        (start_page, end_page) 튜플 목록 — 0-based 인덱스, 끝 포함
    """
    # 권당 기본 페이지 수를 chunk_size 단위로 내림한다
    base_per_part = total_pages // num_parts
    base_rounded = (base_per_part // chunk_size) * chunk_size

    # base_rounded가 0이면 chunk_size보다 적은 페이지/권이므로 1페이지씩 분배
    if base_rounded == 0:
        return _calculate_simple_ranges(total_pages, num_parts)

    # 나머지 페이지를 chunk_size 단위로 앞쪽 권에 추가 분배한다
    remaining = total_pages - base_rounded * num_parts
    extra_chunks = remaining // chunk_size
    leftover = remaining % chunk_size

    ranges: list[tuple[int, int]] = []
    current_page = 0

    for part_idx in range(num_parts):
        size = base_rounded
        # 앞쪽 권에 추가 청크를 분배한다
        if part_idx < extra_chunks:
            size += chunk_size
        # 마지막 권에 나머지 페이지를 포함시킨다
        if part_idx == num_parts - 1:
            size += leftover

        start = current_page
        end = current_page + size - 1
        ranges.append((start, end))
        current_page = end + 1

    return ranges


def _calculate_simple_ranges(
    total_pages: int,
    num_parts: int,
) -> list[tuple[int, int]]:
    """chunk_size 정렬 불가 시 균등 분배로 폴백한다."""
    base = total_pages // num_parts
    remainder = total_pages % num_parts

    ranges: list[tuple[int, int]] = []
    current = 0

    for i in range(num_parts):
        # 나머지 페이지는 앞쪽 권에 1페이지씩 추가한다
        extra = 1 if i < remainder else 0
        size = base + extra
        if size == 0:
            continue
        ranges.append((current, current + size - 1))
        current += size

    return ranges


def _generate_parts(
    doc: object,
    page_ranges: list[tuple[int, int]],
    source_path: Path,
    num_parts: int,
    reporter: ProgressReporter,
) -> list[Path]:
    """각 권 PDF를 생성하고 저장한다."""
    import fitz

    output_paths: list[Path] = []

    for part_idx, (start, end) in enumerate(page_ranges):
        part_num = part_idx + 1

        part_doc = fitz.open()
        try:
            part_doc.insert_pdf(
                doc,  # type: ignore[arg-type]
                from_page=start,
                to_page=end,
            )

            part_path = _generate_part_path(source_path, part_num)
            try:
                part_doc.save(str(part_path))
            except Exception as exc:
                raise SplitError(
                    code=ErrorCodes.SPLIT_FAILED,
                    detail=f"권{part_num} 저장 실패: {exc}",
                ) from exc
        finally:
            part_doc.close()

        output_paths.append(part_path)

        # Flutter에 현재 권 완료 진행률을 보고한다 (1-based)
        reporter.report_split_progress(
            current_part=part_num,
            total_parts=num_parts,
            start_page=start + 1,
            end_page=end + 1,
        )

    return output_paths


def _generate_part_path(source_path: Path, part_num: int) -> Path:
    """원본 파일명을 기반으로 분할 권의 출력 경로를 생성한다.

    규칙: book.pdf → book_part1.pdf, book_part2.pdf, ...
    """
    stem = source_path.stem
    suffix = source_path.suffix
    parent = source_path.parent
    return parent / f"{stem}_part{part_num}{suffix}"


def _handle_single_part(
    source_path: Path,
    reporter: ProgressReporter,
) -> list[Path]:
    """num_parts=1인 경우 분할 없이 원본 경로를 그대로 반환한다."""
    reporter.report_split_complete([str(source_path)])
    return [source_path]
