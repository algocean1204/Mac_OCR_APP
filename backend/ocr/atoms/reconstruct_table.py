# 표 구조 재구성 모듈
# 표 영역과 겹치는 OCR 블록을 행·열 순서로 재조립하여 탭 구분 텍스트로 반환한다
# 비-표 블록은 그대로 통과시킨다
# 격자 데이터가 있을 때는 열 경계 정렬과 적응형 Y 허용 오차를 사용한다
from __future__ import annotations

from backend.ocr.atoms.align_table_columns import assign_cells_to_columns
from backend.ocr.atoms.compute_row_tolerance import compute_adaptive_y_tolerance
from backend.ocr.atoms.detect_table_region import TableRegion
from backend.ocr.grounding_parser import OcrBlock

# Y 좌표 근접성 기본 임계값 — 이 값 이내의 블록은 같은 행으로 묶는다 (정규화 좌표 기준)
_ROW_Y_TOLERANCE: int = 15

# 표 블록의 block_type 식별자
_TABLE_ROW_TYPE: str = "table_row"


def reconstruct_table_text(
    blocks: list[OcrBlock],
    table_regions: list[TableRegion],
    page_width: int,
    page_height: int,
) -> list[OcrBlock]:
    """표 영역과 겹치는 블록들의 텍스트를 구조화된 형태로 재구성한다.

    표 영역에 속하는 블록들을 Y좌표로 행 그룹화하고,
    각 행 내에서 X좌표로 열 정렬한 뒤 탭으로 구분한다.
    TableRegion에 격자 데이터(h/v 선 위치)가 있으면 적응형 허용 오차와
    열 경계 정렬을 사용하여 더 정확한 표 재구성을 수행한다.
    비-표 블록은 그대로 유지한다.

    Args:
        blocks: 원본 OCR 블록 목록
        table_regions: 감지된 표 영역 목록 (격자 데이터 포함 가능)
        page_width: 페이지 너비 (픽셀) — 정규화 좌표 변환에 사용
        page_height: 페이지 높이 (픽셀) — 정규화 좌표 변환에 사용

    Returns:
        재구성된 OCR 블록 목록
    """
    if not table_regions:
        # 표 영역이 없으면 원본 블록을 그대로 반환한다
        return blocks

    table_blocks: list[OcrBlock] = []
    non_table_blocks: list[OcrBlock] = []

    for block in blocks:
        if _overlaps_any_region(block, table_regions, page_width, page_height):
            table_blocks.append(block)
        else:
            non_table_blocks.append(block)

    if not table_blocks:
        return blocks

    # 첫 번째 표 영역의 격자 데이터를 사용하여 적응형 허용 오차를 계산한다
    primary_region = table_regions[0]
    y_tolerance = _resolve_y_tolerance(primary_region, page_height)

    # 수직 선 위치를 정규화 좌표로 변환하여 열 경계로 사용한다
    col_boundaries_norm = _resolve_col_boundaries(primary_region, page_width)

    reconstructed = _group_and_merge_rows(table_blocks, y_tolerance, col_boundaries_norm)
    return non_table_blocks + reconstructed


def _overlaps_any_region(
    block: OcrBlock,
    table_regions: list[TableRegion],
    page_width: int,
    page_height: int,
) -> bool:
    """블록이 하나 이상의 표 영역과 겹치는지 확인한다."""
    for region in table_regions:
        if _block_overlaps_region(block, region, page_width, page_height):
            return True
    return False


def _block_overlaps_region(
    block: OcrBlock,
    region: TableRegion,
    page_width: int,
    page_height: int,
) -> bool:
    """블록의 정규화 좌표와 표 영역(픽셀)을 같은 좌표계로 변환하여 겹침을 판단한다.

    표 영역을 정규화 좌표(0~999)로 변환한 뒤 블록 bbox_norm과 비교한다.
    """
    if page_width <= 0 or page_height <= 0:
        return False

    # 표 영역을 정규화 좌표로 변환한다
    rx1 = int(region.x / page_width * 999)
    ry1 = int(region.y / page_height * 999)
    rx2 = int((region.x + region.width) / page_width * 999)
    ry2 = int((region.y + region.height) / page_height * 999)

    bx1, by1, bx2, by2 = block.bbox_norm

    # 두 사각형이 겹치지 않는 조건의 반대를 반환한다
    no_overlap = bx2 < rx1 or bx1 > rx2 or by2 < ry1 or by1 > ry2
    return not no_overlap


def _resolve_y_tolerance(region: TableRegion, page_height: int) -> int:
    """TableRegion의 격자 데이터가 있으면 적응형 허용 오차를 계산하고,
    없으면 기본값을 반환한다."""
    if region.h_line_positions and page_height > 0:
        return compute_adaptive_y_tolerance(
            region.h_line_positions, page_height, _ROW_Y_TOLERANCE
        )
    return _ROW_Y_TOLERANCE


def _resolve_col_boundaries(region: TableRegion, page_width: int) -> list[int]:
    """TableRegion의 수직 선 위치를 정규화 좌표(0~999)로 변환하여 열 경계를 반환한다.

    격자 데이터가 없거나 변환이 불가능하면 빈 목록을 반환한다.
    """
    if not region.v_line_positions or page_width <= 0:
        return []
    # 픽셀 x 좌표를 정규화 좌표(0~999)로 변환한다
    return [int(px / page_width * 999) for px in region.v_line_positions]


def _group_and_merge_rows(
    table_blocks: list[OcrBlock],
    y_tolerance: int = _ROW_Y_TOLERANCE,
    col_boundaries_norm: list[int] | None = None,
) -> list[OcrBlock]:
    """표 블록을 Y좌표로 행 그룹화하고 각 행을 탭 구분 단일 블록으로 합친다.

    col_boundaries_norm이 제공되면 열 경계 기반 셀 할당을 사용하여
    빈 셀을 포함한 정확한 표 구조를 재구성한다.
    """
    # Y 중심값 기준으로 정렬한다
    sorted_blocks = sorted(
        table_blocks, key=lambda b: (b.bbox_norm[1] + b.bbox_norm[3]) // 2
    )

    rows: list[list[OcrBlock]] = _group_by_y_proximity(sorted_blocks, y_tolerance)
    result: list[OcrBlock] = []

    for row in rows:
        merged = _merge_row_to_block(row, col_boundaries_norm or [])
        result.append(merged)

    return result


def _group_by_y_proximity(
    sorted_blocks: list[OcrBlock],
    tolerance: int = _ROW_Y_TOLERANCE,
) -> list[list[OcrBlock]]:
    """Y 중심값이 tolerance 이내인 블록들을 같은 행으로 묶는다."""
    if not sorted_blocks:
        return []

    rows: list[list[OcrBlock]] = []
    current_row: list[OcrBlock] = [sorted_blocks[0]]

    for block in sorted_blocks[1:]:
        prev_y_center = _y_center(current_row[-1])
        curr_y_center = _y_center(block)

        if abs(curr_y_center - prev_y_center) <= tolerance:
            current_row.append(block)
        else:
            rows.append(current_row)
            current_row = [block]

    rows.append(current_row)
    return rows


def _merge_row_to_block(
    row: list[OcrBlock],
    col_boundaries_norm: list[int],
) -> OcrBlock:
    """한 행의 블록들을 X좌표 순으로 정렬하고 탭 구분 텍스트로 합친다.

    col_boundaries_norm이 충분한 경우(최소 2개) 열 경계 기반 셀 할당을 사용하여
    빈 셀도 포함한 완전한 행 텍스트를 생성한다.
    열 경계가 없으면 기존 방식대로 X 순서 정렬 후 탭 구분한다.

    빈 텍스트 블록을 필터링하지 않아 빈 셀 위치를 보존한다.
    """
    # bbox_norm: 행 전체를 감싸는 최소 경계 박스 계산
    x1 = min(b.bbox_norm[0] for b in row)
    y1 = min(b.bbox_norm[1] for b in row)
    x2 = max(b.bbox_norm[2] for b in row)
    y2 = max(b.bbox_norm[3] for b in row)

    if len(col_boundaries_norm) >= 2:
        # 열 경계 기반 셀 할당 — 빈 셀도 보존한다
        cell_texts = assign_cells_to_columns(row, col_boundaries_norm)
        merged_text = "\t".join(cell_texts)
    else:
        # 열 경계 없음 — X좌표 순 단순 정렬로 처리한다
        sorted_row = sorted(row, key=lambda b: b.bbox_norm[0])
        # 빈 셀도 빈 문자열로 포함하여 구조를 보존한다
        merged_text = "\t".join(b.text.strip() for b in sorted_row)

    return OcrBlock(
        text=merged_text,
        block_type=_TABLE_ROW_TYPE,
        bbox_norm=(x1, y1, x2, y2),
    )


def _y_center(block: OcrBlock) -> int:
    """블록의 Y 중심 좌표를 반환한다."""
    return (block.bbox_norm[1] + block.bbox_norm[3]) // 2
