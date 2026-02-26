# PDF 이미지 추출 모듈
# PyMuPDF(fitz)를 사용하여 PDF 페이지를 PIL Image로 변환한다
# 한 번에 한 페이지만 처리하여 메모리 사용을 최소화한다
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import PdfInputError

if TYPE_CHECKING:
    import fitz


class PdfExtractor:
    """PDF 파일에서 페이지별로 이미지를 추출한다."""

    def __init__(self, dpi: int = 200) -> None:
        # DPI 설정 — 높을수록 OCR 품질이 좋아지나 메모리를 더 사용한다
        self._dpi: int = dpi
        self._doc: fitz.Document | None = None
        self._page_count: int = 0

    def open(self, pdf_path: Path) -> int:
        """PDF 파일을 열고 총 페이지 수를 반환한다.

        Args:
            pdf_path: 열 PDF 파일 경로

        Returns:
            총 페이지 수

        Raises:
            PdfInputError: PDF 열기 실패 시
        """
        import fitz

        try:
            self._doc = fitz.open(str(pdf_path))
        except Exception as exc:
            raise PdfInputError(
                code=ErrorCodes.PDF_CANNOT_OPEN,
                detail=f"fitz.open 실패: {exc}",
            ) from exc

        self._page_count = len(self._doc)

        if self._page_count == 0:
            raise PdfInputError(
                code=ErrorCodes.PDF_NO_CONTENT,
                detail="PDF에 페이지가 없음",
            )

        return self._page_count

    def extract_page_image(self, page_num: int) -> Image.Image:
        """지정된 페이지를 PIL Image로 추출한다.

        메모리 효율을 위해 Pixmap을 즉시 해제한다.

        Args:
            page_num: 0-based 페이지 번호

        Returns:
            PIL Image 객체 (RGB 모드)

        Raises:
            PdfInputError: 페이지 추출 실패 시
        """
        if self._doc is None:
            raise PdfInputError(
                code=ErrorCodes.PDF_CANNOT_OPEN,
                detail="PDF가 열리지 않은 상태에서 페이지 추출 시도",
            )

        try:
            return self._render_page(page_num)
        except PdfInputError:
            raise
        except Exception as exc:
            raise PdfInputError(
                code=ErrorCodes.PDF_CANNOT_OPEN,
                detail=f"페이지 {page_num + 1} 렌더링 실패: {exc}",
            ) from exc

    def _render_page(self, page_num: int) -> Image.Image:
        """PyMuPDF로 페이지를 렌더링하고 PIL Image로 변환한다.

        PNG 인코딩/디코딩을 거치지 않고 raw 픽셀 데이터를 직접 전달하여
        불필요한 압축 오버헤드를 제거한다.
        """
        import fitz

        page = self._doc.load_page(page_num)  # type: ignore[union-attr]

        # DPI를 기반으로 렌더링 행렬을 계산한다 (기본 PDF 해상도는 72 DPI)
        scale: float = self._dpi / 72.0
        matrix = fitz.Matrix(scale, scale)

        # 페이지를 픽셀맵으로 렌더링한다
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        # raw 픽셀 데이터에서 PIL Image를 직접 생성한다 (PNG 압축/해제 생략)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        pix = None  # 메모리 즉시 해제

        return image

    def get_page_size(self, page_num: int) -> tuple[float, float]:
        """페이지의 원본 크기를 포인트(pt) 단위로 반환한다.

        Returns:
            (width_pt, height_pt) 튜플
        """
        if self._doc is None:
            return (595.0, 842.0)  # A4 기본값

        page = self._doc.load_page(page_num)
        rect = page.rect
        return (rect.width, rect.height)

    def close(self) -> None:
        """PDF 문서를 닫고 메모리를 해제한다."""
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def __enter__(self) -> "PdfExtractor":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
