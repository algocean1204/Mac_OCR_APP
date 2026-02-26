# grounding 출력 파서 모듈
# DeepSeek-OCR-2의 <|ref|>/<|det|> 포맷을 파싱하여 OcrBlock 리스트로 변환한다
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.ocr.atoms.detect_truncation import detect_truncation


@dataclass
class OcrBlock:
    """OCR 인식 결과의 단일 블록을 표현한다.

    Attributes:
        text: 실제 텍스트 내용
        block_type: 블록 유형 (text, table, title, sub_title 등)
        bbox_norm: 정규화 좌표 (x1, y1, x2, y2) — 0~999 범위
        truncated: 토큰 한도로 인해 이 블록에서 출력이 잘렸는지 여부
    """
    text: str
    block_type: str
    bbox_norm: tuple[int, int, int, int]
    truncated: bool = False


# <|ref|>TYPE<|/ref|><|det|>[[x1, y1, x2, y2]]<|/det|> 패턴
_REF_DET_PATTERN: re.Pattern[str] = re.compile(
    r"<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>\[\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\]\]<\|/det\|>"
)

# 모델 출력의 첫 블록에서 <|ref|> 태그가 누락되는 패턴
# 모델이 <|Assistant|>: 직후 바로 TYPE<|/ref|>...로 시작하는 경우를 포착한다
_FIRST_BLOCK_PATTERN: re.Pattern[str] = re.compile(
    r"^([\w_]+)<\|/ref\|>\s*<\|det\|>\[\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\]\]<\|/det\|>"
)


def parse_grounding_output(raw: str, max_tokens: int = 16384) -> list[OcrBlock]:
    """grounding 모드 출력을 파싱하여 OcrBlock 리스트로 변환한다.

    파싱 완료 후 잘림(truncation) 여부를 검사하고,
    잘림이 감지되면 마지막 블록의 truncated 플래그를 True로 설정한다.

    Args:
        raw: 모델의 원시 grounding 출력 문자열
        max_tokens: 모델에 설정된 최대 토큰 수 (잘림 감지 휴리스틱에 사용)

    Returns:
        파싱된 OcrBlock 리스트 (순서 보존)
    """
    blocks: list[OcrBlock] = []

    # 모든 ref/det 매치 위치를 찾는다
    matches = list(_REF_DET_PATTERN.finditer(raw))
    if not matches:
        return blocks

    # 첫 번째 블록이 <|ref|> 없이 시작하는 경우를 처리한다
    # 모델이 TYPE<|/ref|><|det|>...로 시작하면 첫 블록의 텍스트가 누락된다
    first_block = _extract_leading_block(raw, matches[0].start())
    if first_block is not None:
        blocks.append(first_block)

    for i, match in enumerate(matches):
        block_type = match.group(1).strip()
        x1 = int(match.group(2))
        y1 = int(match.group(3))
        x2 = int(match.group(4))
        y2 = int(match.group(5))

        # 텍스트 영역: 현재 매치 끝 ~ 다음 매치 시작 (또는 문자열 끝)
        text_start = match.end()
        text_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        text = raw[text_start:text_end].strip()

        # 빈 텍스트 블록은 건너뛴다
        if not text:
            continue

        # 좌표 유효성 기본 검증 (0~999 범위)
        bbox = _clamp_bbox(x1, y1, x2, y2)

        blocks.append(OcrBlock(
            text=text,
            block_type=block_type,
            bbox_norm=bbox,
        ))

    # 잘림 감지 — 마지막 블록에 플래그를 설정한다
    if blocks and detect_truncation(raw, max_tokens):
        blocks[-1].truncated = True

    return blocks


def _extract_leading_block(raw: str, first_match_start: int) -> OcrBlock | None:
    """<|ref|> 태그 없이 시작하는 첫 번째 블록을 추출한다.

    모델이 TYPE<|/ref|><|det|>[[x1,y1,x2,y2]]<|/det|>텍스트... 형식으로
    출력을 시작하면 정규 매치가 이 블록을 놓친다.
    이 함수는 첫 정규 매치 이전의 텍스트에서 해당 패턴을 찾아 OcrBlock으로 반환한다.

    Args:
        raw: 모델의 원시 grounding 출력
        first_match_start: 첫 정규 <|ref|> 매치의 시작 위치

    Returns:
        추출된 OcrBlock, 또는 해당 패턴이 없으면 None
    """
    # 첫 정규 매치 이전의 텍스트만 검사한다
    prefix = raw[:first_match_start]
    leading_match = _FIRST_BLOCK_PATTERN.match(prefix)
    if not leading_match:
        return None

    block_type = leading_match.group(1).strip()
    x1 = int(leading_match.group(2))
    y1 = int(leading_match.group(3))
    x2 = int(leading_match.group(4))
    y2 = int(leading_match.group(5))

    text = prefix[leading_match.end():].strip()
    if not text:
        return None

    bbox = _clamp_bbox(x1, y1, x2, y2)
    return OcrBlock(text=text, block_type=block_type, bbox_norm=bbox)


def _clamp_bbox(
    x1: int, y1: int, x2: int, y2: int,
) -> tuple[int, int, int, int]:
    """좌표를 0~999 범위로 클램핑하고 논리적 유효성을 보장한다."""
    x1 = max(0, min(x1, 999))
    y1 = max(0, min(y1, 999))
    x2 = max(0, min(x2, 999))
    y2 = max(0, min(y2, 999))
    # x2 > x1, y2 > y1 보장
    if x2 <= x1:
        x2 = min(x1 + 1, 999)
    if y2 <= y1:
        y2 = min(y1 + 1, 999)
    return (x1, y1, x2, y2)


def norm_to_pdf_coords(
    bbox_norm: tuple[int, int, int, int],
    img_width: int,
    img_height: int,
    page_width_pt: float,
    page_height_pt: float,
) -> tuple[float, float, float, float]:
    """정규화 좌표(0~999)를 PDF 포인트 좌표로 변환한다.

    변환 과정:
    1) 정규화 → 비율: ratio = norm / 999
    2) 비율 → PDF 포인트: pt = ratio * page_size_pt
    3) Y축 뒤집기: reportlab은 좌측 하단이 원점(0,0)

    Args:
        bbox_norm: 정규화 좌표 (x1, y1, x2, y2), 0~999
        img_width: 원본 이미지 너비 (픽셀) — 현재 미사용, 향후 보정용
        img_height: 원본 이미지 높이 (픽셀) — 현재 미사용, 향후 보정용
        page_width_pt: PDF 페이지 너비 (포인트)
        page_height_pt: PDF 페이지 높이 (포인트)

    Returns:
        (x_pdf, y_pdf, w_pdf, h_pdf) — reportlab 좌표계 (좌측 하단 원점)
    """
    x1_n, y1_n, x2_n, y2_n = bbox_norm

    # 정규화 좌표 → PDF 포인트 좌표
    x_left = (x1_n / 999.0) * page_width_pt
    y_top = (y1_n / 999.0) * page_height_pt
    x_right = (x2_n / 999.0) * page_width_pt
    y_bottom = (y2_n / 999.0) * page_height_pt

    # 박스 크기 계산
    w = x_right - x_left
    h = y_bottom - y_top

    # Y축 뒤집기 — reportlab은 좌측 하단이 원점이므로 y_top을 뒤집는다
    y_pdf = page_height_pt - y_bottom

    return (x_left, y_pdf, w, h)
