# 단일 페이지 처리 모듈
# 이미지 추출 → OCR 추론 → PDF 기록 → 메모리 해제를 담당한다
from __future__ import annotations

from PIL import Image

from backend.errors.exceptions import MemoryLimitError
from backend.errors.handler import ErrorHandler
from backend.memory.manager import MemoryManager
from backend.ocr.engine import OcrEngine
from backend.pdf.extractor import PdfExtractor
from backend.pdf.generator import PdfGenerator
from backend.progress.reporter import ProgressReporter


class PageProcessor:
    """단일 페이지의 OCR 처리 흐름을 담당하는 클래스다."""

    def __init__(
        self,
        reporter: ProgressReporter,
        error_handler: ErrorHandler,
        memory: MemoryManager,
    ) -> None:
        self._reporter: ProgressReporter = reporter
        self._error_handler: ErrorHandler = error_handler
        self._memory: MemoryManager = memory

    def process(
        self,
        page_num: int,
        total_pages: int,
        extractor: PdfExtractor,
        ocr_engine: OcrEngine,
        generator: PdfGenerator,
        ocr_timeout: int = 120,
    ) -> None:
        """단일 페이지를 처리한다. 실패 시 이미지만으로 대체한다.

        Args:
            page_num: 0-based 페이지 번호
            total_pages: 전체 페이지 수
            extractor: PDF 이미지 추출기
            ocr_engine: OCR 추론 엔진
            generator: PDF 생성기
            ocr_timeout: 페이지당 OCR 타임아웃 (초)

        Raises:
            MemoryLimitError: 메모리 치명 수준 초과 시 (복구 불가)
        """
        image: Image.Image | None = None
        ocr_text: str | None = None

        try:
            image, ocr_text = self._run_ocr_pipeline(
                page_num, total_pages, extractor, ocr_engine, ocr_timeout
            )
            self._write_page(image, ocr_text, page_num, total_pages, extractor, generator)

        except MemoryLimitError:
            # 메모리 치명 에러는 상위로 전파하여 파이프라인을 중단시킨다
            raise

        except Exception as exc:
            # 페이지 실패는 원본 이미지만으로 계속 진행한다
            self._error_handler.handle_page_error(page_num, exc)
            self._write_fallback_page(image, page_num, extractor, generator)

        finally:
            # 성공/실패 모두 메모리를 즉시 해제한다 (아키텍처 문서 9.2절)
            self._memory.cleanup_page_memory(image, ocr_text)
            self._report_page_complete(page_num, total_pages)
            self._check_memory()

    def _run_ocr_pipeline(
        self,
        page_num: int,
        total_pages: int,
        extractor: PdfExtractor,
        ocr_engine: OcrEngine,
        ocr_timeout: int,
    ) -> tuple[Image.Image, str]:
        """이미지 추출 + OCR 추론 파이프라인을 실행하고 결과를 반환한다."""
        # 이미지 추출 단계
        self._reporter.report_progress(
            page_num + 1, total_pages, "extracting_image",
            self._memory.current_mb(),
        )
        image = extractor.extract_page_image(page_num)

        # OCR 추론 단계
        self._reporter.report_progress(
            page_num + 1, total_pages, "ocr_processing",
            self._memory.current_mb(),
        )
        ocr_text = ocr_engine.run_ocr(image, timeout_seconds=ocr_timeout)
        return image, ocr_text

    def _write_page(
        self,
        image: Image.Image,
        ocr_text: str,
        page_num: int,
        total_pages: int,
        extractor: PdfExtractor,
        generator: PdfGenerator,
    ) -> None:
        """OCR 결과를 출력 PDF에 기록한다."""
        self._reporter.report_progress(
            page_num + 1, total_pages, "writing_output",
            self._memory.current_mb(),
        )
        page_width, page_height = extractor.get_page_size(page_num)
        generator.add_page(image, ocr_text, page_width, page_height)

    def _write_fallback_page(
        self,
        image: Image.Image | None,
        page_num: int,
        extractor: PdfExtractor,
        generator: PdfGenerator,
    ) -> None:
        """OCR 실패 시 이미지만으로 페이지를 추가한다."""
        if image is None:
            return
        try:
            page_width, page_height = extractor.get_page_size(page_num)
            generator.add_image_only_page(image, page_width, page_height)
        except Exception:
            pass

    def _report_page_complete(self, page_num: int, total_pages: int) -> None:
        """페이지 완료 진행률을 보고한다."""
        self._reporter.report_progress(
            page_num + 1, total_pages, "page_complete",
            self._memory.current_mb(),
        )

    def _check_memory(self) -> None:
        """메모리 상태를 확인하고 필요 시 경고 또는 종료한다."""
        self._memory.check_and_act(self._error_handler)
