# 검색 가능 PDF 생성 모듈
# reportlab으로 단일 페이지 PDF를 만들고 PyMuPDF로 즉시 병합한다
# 청크 단위(최대 10페이지)로 사용하여 메모리 누적을 방지한다
from __future__ import annotations

import io
import logging
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from reportlab.lib.colors import Color, black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import OutputError
from backend.ocr.grounding_parser import OcrBlock, norm_to_pdf_coords
from backend.ocr.text_cleaner import clean_text
from backend.pdf.atoms.render_table_blocks import (
    format_table_row_text,
    group_table_blocks_into_rows,
    is_table_block,
)

logger = logging.getLogger(__name__)

# 번들된 TTF 폰트로 한국어/CJK 텍스트 검색을 지원한다
# AppleGothic.ttf — macOS 기본 한국어 고딕체, backend/fonts/ 에 번들된다
_BUNDLED_FONT_PATH: Path = (
    Path(__file__).parent.parent / "fonts" / "AppleGothic.ttf"
)
_CJK_FONT_NAME: str = "Helvetica"

# 폰트 메트릭 — drawString baseline 정밀 배치에 사용
# ascent: baseline 위 높이 비율, descent: baseline 아래 높이 비율
_FONT_ASCENT_RATIO: float = 0.766
_FONT_DESCENT_RATIO: float = 0.234

# 번들된 TTF 폰트 등록 시도 — 실패 시 Helvetica 폴백
if _BUNDLED_FONT_PATH.exists():
    try:
        pdfmetrics.registerFont(TTFont("AppleGothic", str(_BUNDLED_FONT_PATH)))
        _CJK_FONT_NAME = "AppleGothic"
        # 실제 폰트 메트릭에서 ascent/descent 비율을 계산한다
        _face = pdfmetrics.getFont("AppleGothic").face
        _em = _face.ascent - _face.descent
        if _em > 0:
            _FONT_ASCENT_RATIO = _face.ascent / _em
            _FONT_DESCENT_RATIO = abs(_face.descent) / _em
    except Exception:
        # 폰트 등록 실패 시 기본 Helvetica 를 유지한다 (한국어 검색 불가)
        logger.warning("AppleGothic.ttf 등록 실패 — Helvetica 폴백 사용")


class PdfGenerator:
    """페이지별 이미지+투명 텍스트를 합쳐 검색 가능한 PDF를 생성한다.

    청크 단위(최대 chunk_size 페이지)로 사용하여 메모리 누적을 방지한다.
    각 청크마다 새 인스턴스를 생성하고 save()로 저장한다.
    """

    def __init__(self, output_path: Path) -> None:
        self._output_path: Path = output_path
        self._output_doc: fitz.Document = fitz.open()
        self._page_count: int = 0

    def add_page(
        self,
        image: Image.Image,
        ocr_text: str,
        page_width_pt: float,
        page_height_pt: float,
    ) -> None:
        """이미지와 OCR 텍스트를 하나의 PDF 페이지로 추가한다."""
        try:
            page_buf = _render_single_page(
                image, ocr_text, page_width_pt, page_height_pt
            )
            page_bytes = page_buf.getvalue()
            page_buf.close()

            single_doc = fitz.open("pdf", page_bytes)
            self._output_doc.insert_pdf(single_doc)
            single_doc.close()
            del page_bytes

            self._page_count += 1

        except OutputError:
            raise
        except Exception as exc:
            raise OutputError(
                code=ErrorCodes.OUTPUT_WRITE_FAILED,
                detail=f"페이지 {self._page_count + 1} 추가 실패: {exc}",
            ) from exc

    def add_page_with_blocks(
        self,
        image: Image.Image,
        blocks: list[OcrBlock],
        page_width_pt: float,
        page_height_pt: float,
        img_width: int,
        img_height: int,
    ) -> None:
        """이미지와 좌표 정보가 포함된 OCR 블록으로 PDF 페이지를 추가한다.

        각 블록의 bbox_norm 좌표를 PDF 좌표로 변환하여 텍스트를 정확한 위치에
        투명하게 배치한다. blocks 가 비어 있을 때도 이미지 페이지를 정상 추가한다.
        """
        try:
            page_buf = _render_single_page_with_blocks(
                image, blocks, page_width_pt, page_height_pt, img_width, img_height
            )
            page_bytes = page_buf.getvalue()
            page_buf.close()

            single_doc = fitz.open("pdf", page_bytes)
            self._output_doc.insert_pdf(single_doc)
            single_doc.close()
            del page_bytes

            self._page_count += 1

        except OutputError:
            raise
        except Exception as exc:
            raise OutputError(
                code=ErrorCodes.OUTPUT_WRITE_FAILED,
                detail=f"블록 기반 페이지 {self._page_count + 1} 추가 실패: {exc}",
            ) from exc

    def save(self) -> None:
        """PDF 파일을 디스크에 최종 저장한다."""
        if self._page_count == 0:
            raise OutputError(
                code=ErrorCodes.OUTPUT_WRITE_FAILED,
                detail="저장할 페이지가 없음",
            )
        try:
            self._output_doc.save(str(self._output_path))
            self._output_doc.close()
        except Exception as exc:
            raise OutputError(
                code=ErrorCodes.OUTPUT_WRITE_FAILED,
                detail=f"PDF 저장 실패: {exc}",
            ) from exc

    def add_image_only_page(
        self,
        image: Image.Image,
        page_width_pt: float,
        page_height_pt: float,
    ) -> None:
        """OCR 실패 시 텍스트 없이 이미지만으로 페이지를 추가한다."""
        self.add_page(image, "", page_width_pt, page_height_pt)

    def add_page_with_block_results(
        self,
        image: Image.Image,
        block_results: list[dict],
        page_width_pt: float,
        page_height_pt: float,
    ) -> None:
        """블록 파이프라인 OCR 결과로 PDF 페이지를 추가한다.

        각 블록의 정규화 좌표(0~1 float)를 PDF 좌표로 변환하여
        텍스트를 정확한 위치에 투명하게 배치한다.

        Args:
            image: 원본 페이지 이미지
            block_results: BlockOcrResult를 직렬화한 딕셔너리 목록
                각 항목: {"text": str, "bbox_norm": [x1,y1,x2,y2], ...}
            page_width_pt: PDF 페이지 너비 (포인트)
            page_height_pt: PDF 페이지 높이 (포인트)
        """
        try:
            page_buf = _render_page_with_block_results(
                image, block_results, page_width_pt, page_height_pt
            )
            page_bytes = page_buf.getvalue()
            page_buf.close()

            single_doc = fitz.open("pdf", page_bytes)
            self._output_doc.insert_pdf(single_doc)
            single_doc.close()
            del page_bytes

            self._page_count += 1

        except OutputError:
            raise
        except Exception as exc:
            raise OutputError(
                code=ErrorCodes.OUTPUT_WRITE_FAILED,
                detail=f"블록 결과 기반 페이지 {self._page_count + 1} 추가 실패: {exc}",
            ) from exc

    @property
    def page_count(self) -> int:
        """현재 추가된 페이지 수를 반환한다."""
        return self._page_count


def _render_single_page(
    image: Image.Image,
    ocr_text: str,
    page_width: float,
    page_height: float,
) -> io.BytesIO:
    """reportlab으로 단일 페이지 PDF를 BytesIO에 생성하여 반환한다."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width, page_height))

    _draw_image_background(c, image, page_width, page_height)

    if ocr_text and ocr_text.strip():
        _draw_transparent_text_positioned(c, ocr_text, image, page_width, page_height)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _render_single_page_with_blocks(
    image: Image.Image,
    blocks: list[OcrBlock],
    page_width: float,
    page_height: float,
    img_width: int,
    img_height: int,
) -> io.BytesIO:
    """좌표 기반으로 텍스트를 배치한 단일 페이지 PDF를 BytesIO에 생성하여 반환한다.

    기존 _render_single_page 와 달리 OcrBlock 의 bbox_norm 좌표를
    실제 PDF 좌표로 변환하여 각 텍스트를 정확한 위치에 배치한다.
    """
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width, page_height))

    _draw_image_background(c, image, page_width, page_height)

    if blocks:
        _draw_transparent_text_blocks(
            c, blocks, page_width, page_height, img_width, img_height
        )

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _draw_image_background(
    canvas: rl_canvas.Canvas,
    image: Image.Image,
    page_width: float,
    page_height: float,
) -> None:
    """PIL 이미지를 PDF 페이지 전체에 배경으로 그린다.

    PIL Image를 ImageReader에 직접 전달하여 PNG 인코딩 오버헤드를 제거한다.
    """
    from reportlab.lib.utils import ImageReader

    img_reader = ImageReader(image)

    canvas.drawImage(
        img_reader,
        x=0, y=0,
        width=page_width, height=page_height,
        preserveAspectRatio=False,
    )


def _draw_transparent_text_positioned(
    canvas: rl_canvas.Canvas,
    text: str,
    image: Image.Image,
    page_width: float,
    page_height: float,
) -> None:
    """OCR 텍스트를 Tesseract 위치 정보 기반으로 투명하게 배치한다.

    Tesseract로 텍스트 영역을 감지하고, OCR 줄을 해당 영역에 배치한다.
    줄 수 비슷하면 1:1 매칭, 많이 다르면 합쳐서 배치한다.
    """
    from backend.pdf.atoms.extract_line_positions import (
        extract_text_region,
        map_ocr_to_pdf_positions,
    )

    transparent = Color(0, 0, 0, alpha=0)
    canvas.setFillColor(transparent)
    canvas.setStrokeColor(transparent)

    ocr_lines = [line for line in text.split("\n") if line.strip()]
    if not ocr_lines:
        canvas.setFillColor(black)
        canvas.setStrokeColor(black)
        return

    img_w, img_h = image.size
    region = extract_text_region(image)

    if region is not None:
        result = map_ocr_to_pdf_positions(
            region, ocr_lines, img_w, img_h, page_width, page_height,
        )
        _place_lines(canvas, result.lines)
    else:
        _place_lines_distributed(canvas, ocr_lines, page_width, page_height)

    canvas.setFillColor(black)
    canvas.setStrokeColor(black)


def _place_lines(
    canvas: rl_canvas.Canvas,
    placed_lines: list,
) -> None:
    """PlacedLine 목록을 PDF에 배치한다."""
    for pl in placed_lines:
        font_size = max(6.0, min(pl.height * 0.85, 20.0))
        canvas.setFont(_CJK_FONT_NAME, font_size)

        # 텍스트 기준선을 박스 내에서 수직 중앙에 배치한다
        y_line = pl.y + (pl.height - font_size) * 0.5
        if y_line >= 0:
            canvas.drawString(pl.x, y_line, pl.text)


def _place_lines_distributed(
    canvas: rl_canvas.Canvas,
    ocr_lines: list[str],
    page_width: float,
    page_height: float,
) -> None:
    """Tesseract 사용 불가 시 페이지 전체에 균등 분배한다."""
    margin_top = page_height * 0.05
    margin_bottom = page_height * 0.05
    margin_left = page_width * 0.05

    usable_height = page_height - margin_top - margin_bottom
    n_lines = len(ocr_lines)
    line_height = min(usable_height / max(n_lines, 1), 20.0)
    font_size = min(line_height * 0.85, 14.0)

    canvas.setFont(_CJK_FONT_NAME, font_size)

    y_pos = page_height - margin_top - font_size
    for line in ocr_lines:
        if y_pos < margin_bottom:
            break
        canvas.drawString(margin_left, y_pos, line)
        y_pos -= line_height


def _draw_transparent_text_blocks(
    canvas: rl_canvas.Canvas,
    blocks: list[OcrBlock],
    page_width: float,
    page_height: float,
    img_width: int,
    img_height: int,
) -> None:
    """OCR 블록을 정규화 좌표 기반으로 실제 위치에 투명 텍스트로 배치한다.

    표 관련 블록(table_header / table_cell / table_row)은 행 단위로 묶어
    탭 구분 텍스트로 렌더링한다. 나머지 블록은 기존 방식으로 배치한다.
    폰트 크기는 박스 높이에 맞게 동적으로 계산한다.
    """
    transparent = Color(0, 0, 0, alpha=0)
    canvas.setFillColor(transparent)
    canvas.setStrokeColor(transparent)

    table_blocks: list[OcrBlock] = []
    normal_blocks: list[OcrBlock] = []

    # 표 블록과 일반 블록을 분리한다
    for block in blocks:
        if is_table_block(block):
            table_blocks.append(block)
        else:
            normal_blocks.append(block)

    # 일반 블록 렌더링
    for block in normal_blocks:
        _render_normal_block(canvas, block, page_width, page_height, img_width, img_height)

    # 표 블록 렌더링 — 행 단위로 그룹화하여 처리한다
    if table_blocks:
        _render_table_blocks(
            canvas, table_blocks, page_width, page_height, img_width, img_height
        )

    # 이후 렌더링을 위해 기본 색상 복원
    canvas.setFillColor(black)
    canvas.setStrokeColor(black)


def _render_normal_block(
    canvas: rl_canvas.Canvas,
    block: OcrBlock,
    page_width: float,
    page_height: float,
    img_width: int,
    img_height: int,
) -> None:
    """단일 일반 블록을 PDF 좌표에 투명 텍스트로 배치한다."""
    x_pdf, y_pdf, w_pdf, h_pdf = norm_to_pdf_coords(
        block.bbox_norm, img_width, img_height, page_width, page_height
    )

    # 마크다운·프롬프트 누출 문자 제거
    cleaned: str = clean_text(block.text)
    if not cleaned:
        return

    # 멀티라인 텍스트를 줄별로 분리하여 각 줄을 배치한다
    lines = [l.strip() for l in cleaned.split("\n") if l.strip()]
    line_count = max(1, len(lines))

    # 초기 폰트 크기 = 블록 높이 / 줄 수 (상한)
    per_line_h = h_pdf / line_count
    font_size: float = max(3.0, min(per_line_h, 48.0))

    # 텍스트가 블록 너비에 맞도록 축소
    font_size = _fit_font_to_width(lines, font_size, w_pdf, _CJK_FONT_NAME)

    canvas.setFont(_CJK_FONT_NAME, font_size)

    # baseline 정밀 배치 — 각 줄 슬롯의 수직 중앙에 텍스트 배치
    # CRAFT bbox는 실제 글자보다 상하 여유가 있으므로 중앙 정렬이 정확하다
    block_top = y_pdf + h_pdf
    vert_offset = font_size * (_FONT_ASCENT_RATIO - 0.5)
    for i, line in enumerate(lines):
        slot_center = block_top - (i + 0.5) * per_line_h
        baseline_y = slot_center - vert_offset
        if baseline_y < 0:
            break
        canvas.drawString(x_pdf, baseline_y, line)


def _render_table_blocks(
    canvas: rl_canvas.Canvas,
    table_blocks: list[OcrBlock],
    page_width: float,
    page_height: float,
    img_width: int,
    img_height: int,
) -> None:
    """표 블록을 행 단위로 그룹화하고 탭 구분 텍스트로 렌더링한다."""
    rows = group_table_blocks_into_rows(table_blocks)

    for row in rows:
        row_text = format_table_row_text(row)
        if not row_text:
            continue

        cleaned: str = clean_text(row_text)
        if not cleaned:
            continue

        # 행의 전체 bbox를 대표 좌표로 사용한다
        x1 = min(b.bbox_norm[0] for b in row)
        y1 = min(b.bbox_norm[1] for b in row)
        x2 = max(b.bbox_norm[2] for b in row)
        y2 = max(b.bbox_norm[3] for b in row)
        row_bbox = (x1, y1, x2, y2)

        x_pdf, y_pdf, w_pdf, h_pdf = norm_to_pdf_coords(
            row_bbox, img_width, img_height, page_width, page_height
        )

        font_size: float = max(3.0, min(h_pdf, 48.0))
        font_size = _fit_font_to_width(
            [cleaned], font_size, w_pdf, _CJK_FONT_NAME,
        )
        canvas.setFont(_CJK_FONT_NAME, font_size)

        # 수직 중앙 정렬
        slot_center = y_pdf + h_pdf * 0.5
        baseline_y = slot_center - font_size * (_FONT_ASCENT_RATIO - 0.5)
        if baseline_y >= 0:
            canvas.drawString(x_pdf, baseline_y, cleaned)


def _render_page_with_block_results(
    image: Image.Image,
    block_results: list[dict],
    page_width: float,
    page_height: float,
) -> io.BytesIO:
    """블록 파이프라인 결과를 기반으로 단일 페이지 PDF를 생성한다.

    각 블록의 정규화 좌표(0~1 float)를 PDF 좌표로 변환하여
    투명 텍스트를 정확한 위치에 배치한다.
    """
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width, page_height))

    _draw_image_background(c, image, page_width, page_height)

    if block_results:
        transparent = Color(0, 0, 0, alpha=0)
        c.setFillColor(transparent)
        c.setStrokeColor(transparent)

        for br in block_results:
            text = br.get("text", "").strip()
            if not text:
                continue

            bbox = br.get("bbox_norm", [0, 0, 1, 1])
            nx1, ny1, nx2, ny2 = bbox[0], bbox[1], bbox[2], bbox[3]

            # 정규화 좌표(0~1) → PDF 좌표
            x_pdf = nx1 * page_width
            w_pdf = (nx2 - nx1) * page_width
            h_pdf = (ny2 - ny1) * page_height
            y_pdf = page_height - ny2 * page_height  # reportlab 좌하단 원점

            # 마크다운 프롬프트 누출 문자 제거
            cleaned = clean_text(text)
            if not cleaned:
                continue

            # 멀티라인 텍스트를 줄별로 분리하여 렌더링한다
            lines = [l.strip() for l in cleaned.split("\n") if l.strip()]
            if not lines:
                continue

            line_count = len(lines)

            # 초기 폰트 크기 = 블록 높이 / 줄 수 (상한)
            per_line_h = h_pdf / max(line_count, 1)
            font_size: float = max(3.0, min(per_line_h, 48.0))

            # 텍스트가 블록 너비에 맞도록 축소 — 실제 폰트 크기 결정
            # CRAFT bbox 높이 > 실제 폰트 크기이므로 너비 기반이 더 정확
            font_size = _fit_font_to_width(
                lines, font_size, w_pdf, _CJK_FONT_NAME,
            )

            c.setFont(_CJK_FONT_NAME, font_size)

            # baseline 정밀 배치:
            # CRAFT bbox는 실제 글자보다 상하 여유가 있으므로
            # 각 줄 슬롯의 수직 중앙에 텍스트를 배치한다
            block_top = y_pdf + h_pdf
            vert_offset = font_size * (_FONT_ASCENT_RATIO - 0.5)
            for i, line in enumerate(lines):
                slot_center = block_top - (i + 0.5) * per_line_h
                baseline_y = slot_center - vert_offset
                if baseline_y < 0:
                    break
                c.drawString(x_pdf, baseline_y, line)

        c.setFillColor(black)
        c.setStrokeColor(black)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _fit_font_to_width(
    lines: list[str],
    font_size: float,
    max_width: float,
    font_name: str,
) -> float:
    """텍스트가 블록 너비를 초과하지 않도록 폰트 크기를 축소한다.

    가장 긴 줄의 렌더링 너비가 블록 너비를 초과하면
    비례적으로 폰트 크기를 줄여 정확히 맞춘다.
    """
    if max_width <= 0:
        return font_size

    max_text_width: float = 0.0
    for line in lines:
        text_width = pdfmetrics.stringWidth(line, font_name, font_size)
        if text_width > max_text_width:
            max_text_width = text_width

    if max_text_width <= 0:
        return font_size

    # 텍스트가 블록 너비를 초과하면 비례 축소
    if max_text_width > max_width:
        ratio = max_width / max_text_width
        font_size = max(3.0, font_size * ratio)

    return font_size
