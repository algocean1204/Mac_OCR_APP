# 청크 PDF 병합 모듈
# 개별 청크 PDF 파일들을 페이지 순서대로 병합하여 최종 PDF를 생성한다
from __future__ import annotations

from pathlib import Path

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import OutputError


def merge_chunks(chunk_dir: Path, output_path: Path) -> int:
    """청크 PDF 파일들을 페이지 순서대로 병합하여 최종 PDF를 생성한다.

    청크 파일명은 chunk_{시작페이지:06d}.pdf 형식이므로
    파일명 정렬이 곧 페이지 순서다.

    Args:
        chunk_dir: 청크 PDF가 저장된 디렉토리
        output_path: 최종 출력 PDF 경로

    Returns:
        병합된 총 페이지 수

    Raises:
        OutputError: 병합할 청크가 없거나 병합 실패 시
    """
    import fitz

    # 청크 파일을 파일명 순서(=페이지 순서)로 정렬한다
    chunk_paths = sorted(chunk_dir.glob("chunk_*.pdf"))

    if not chunk_paths:
        raise OutputError(
            code=ErrorCodes.OUTPUT_WRITE_FAILED,
            detail="병합할 청크 PDF가 없음",
        )

    try:
        output_doc = fitz.open()
        total_pages: int = 0

        for chunk_path in chunk_paths:
            chunk_doc = fitz.open(str(chunk_path))
            output_doc.insert_pdf(chunk_doc)
            total_pages += len(chunk_doc)
            chunk_doc.close()

        output_doc.save(str(output_path))
        output_doc.close()

    except OutputError:
        raise
    except Exception as exc:
        raise OutputError(
            code=ErrorCodes.OUTPUT_WRITE_FAILED,
            detail=f"청크 병합 실패: {exc}",
        ) from exc

    return total_pages
