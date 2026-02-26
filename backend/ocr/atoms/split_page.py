# 페이지 이미지 분할 모듈
# 잘림이 감지된 페이지를 상/하 두 부분으로 분할하여 재-OCR을 가능하게 한다
from __future__ import annotations

from PIL import Image

# 분할 지점 탐색 범위 — 중앙에서 ±15% 범위 내에서 최적 분할점을 찾는다
_SPLIT_SEARCH_MARGIN: float = 0.15


def split_page_image(
    image: Image.Image,
    overlap_px: int = 50,
) -> list[Image.Image]:
    """페이지 이미지를 상/하 두 부분으로 분할한다.

    텍스트 행을 가로지르지 않도록 중앙 부근에서 분할한다.
    overlap_px만큼 겹침 영역을 두어 경계 텍스트 손실을 방지한다.

    Args:
        image: 분할할 원본 PIL Image 객체
        overlap_px: 상/하 이미지가 공유할 겹침 픽셀 수

    Returns:
        [상단 이미지, 하단 이미지] — 각각 독립적으로 OCR 가능
    """
    width, height = image.size
    split_y = _find_split_point(image, height)

    # 상단: 0 ~ split_y + overlap
    top_bottom = min(split_y + overlap_px, height)
    top_half = image.crop((0, 0, width, top_bottom))

    # 하단: split_y - overlap ~ height
    bottom_top = max(split_y - overlap_px, 0)
    bottom_half = image.crop((0, bottom_top, width, height))

    return [top_half, bottom_half]


def _find_split_point(image: Image.Image, height: int) -> int:
    """이미지 내 최적 분할 행(y좌표)을 탐색한다.

    수평 투영법(horizontal projection)으로 중앙 ±15% 구간에서
    흰 공간이 가장 많은 행을 분할 지점으로 선택한다.
    명확한 간격이 없으면 정확한 중앙값을 반환한다.
    """
    midpoint = height // 2
    search_start = int(height * (0.5 - _SPLIT_SEARCH_MARGIN))
    search_end = int(height * (0.5 + _SPLIT_SEARCH_MARGIN))

    gray = image.convert("L")
    width = image.size[0]

    best_row = midpoint
    best_whiteness = -1

    for row in range(search_start, search_end):
        # 해당 행의 픽셀 밝기 합산 — 높을수록 흰 공간(빈 행)
        row_pixels = gray.crop((0, row, width, row + 1))
        whiteness = sum(row_pixels.getdata())  # type: ignore[arg-type]

        if whiteness > best_whiteness:
            best_whiteness = whiteness
            best_row = row

    return best_row


def remap_blocks_to_original(
    blocks: list,
    half_index: int,
    split_y_norm: int,
    total_height: int,
    half_height: int,
) -> list:
    """분할된 이미지에서 추출한 블록의 좌표를 원본 이미지 기준으로 재매핑한다.

    분할 이미지에서 얻은 정규화 좌표(0~999)를 원본 전체 이미지의
    좌표 공간으로 선형 변환한다.

    Args:
        blocks: 분할 이미지에서 파싱된 OcrBlock 리스트
        half_index: 0 = 상단 이미지, 1 = 하단 이미지
        split_y_norm: 원본 이미지 기준 분할 y좌표의 정규화 값 (0~999)
        total_height: 원본 이미지 전체 높이 (픽셀)
        half_height: 분할 이미지 높이 (픽셀)

    Returns:
        좌표가 원본 기준으로 재매핑된 새 OcrBlock 리스트
    """
    from backend.ocr.grounding_parser import OcrBlock

    remapped: list[OcrBlock] = []

    for block in blocks:
        new_bbox = _remap_bbox(
            block.bbox_norm,
            half_index=half_index,
            split_y_norm=split_y_norm,
            total_height=total_height,
            half_height=half_height,
        )
        remapped.append(OcrBlock(
            text=block.text,
            block_type=block.block_type,
            bbox_norm=new_bbox,
            truncated=block.truncated,
        ))

    return remapped


def _remap_bbox(
    bbox_norm: tuple[int, int, int, int],
    half_index: int,
    split_y_norm: int,
    total_height: int,
    half_height: int,
) -> tuple[int, int, int, int]:
    """단일 bbox 좌표를 원본 이미지 좌표 공간으로 변환한다.

    분할 이미지의 y 좌표(0~999)를 원본 이미지의 y 범위로 선형 스케일링한다.
    - 상단 이미지(half_index=0): y 범위는 0 ~ split_y_norm
    - 하단 이미지(half_index=1): y 범위는 split_y_norm ~ 999
    """
    x1_n, y1_n, x2_n, y2_n = bbox_norm

    # 분할 이미지 내 y 비율 계산
    half_y_range = _compute_half_y_range(
        half_index, split_y_norm, total_height, half_height
    )
    y_origin, y_span = half_y_range

    # 분할 이미지 정규화 y → 원본 이미지 정규화 y로 변환
    new_y1 = int(y_origin + (y1_n / 999.0) * y_span)
    new_y2 = int(y_origin + (y2_n / 999.0) * y_span)

    # 범위 보정
    new_y1 = max(0, min(new_y1, 999))
    new_y2 = max(0, min(new_y2, 999))
    if new_y2 <= new_y1:
        new_y2 = min(new_y1 + 1, 999)

    return (x1_n, new_y1, x2_n, new_y2)


def _compute_half_y_range(
    half_index: int,
    split_y_norm: int,
    total_height: int,
    half_height: int,
) -> tuple[int, int]:
    """분할 이미지의 y 좌표가 원본에서 차지하는 범위를 계산한다.

    Returns:
        (y_origin, y_span) — 원본 정규화 좌표 기준 시작점과 범위
    """
    if half_index == 0:
        # 상단 이미지: 0 ~ split_y_norm 범위에 매핑
        y_origin = 0
        y_span = split_y_norm
    else:
        # 하단 이미지: split_y_norm ~ 999 범위에 매핑
        y_origin = split_y_norm
        y_span = 999 - split_y_norm

    return (y_origin, y_span)
