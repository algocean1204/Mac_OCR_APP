# 표 블록 렌더링 원자적 모듈
# 표 관련 OCR 블록을 행 단위로 그룹화하고 탭 구분 텍스트를 생성한다
# generator.py의 _draw_transparent_text_blocks 에서 호출한다
# 개별 셀 bbox 위치 기반 렌더링을 지원하여 열 정렬 정확도를 높인다
from __future__ import annotations

from backend.ocr.grounding_parser import OcrBlock

# 표 블록으로 인식하는 block_type 값 목록
_TABLE_BLOCK_TYPES: frozenset[str] = frozenset(
    {"table_header", "table_cell", "table_row"}
)

# 행 그룹화에 사용하는 Y좌표 근접성 기본 임계값 (정규화 좌표 기준)
_DEFAULT_Y_TOLERANCE: int = 15


def is_table_block(block: OcrBlock) -> bool:
    """블록이 표 관련 타입인지 확인한다."""
    return block.block_type in _TABLE_BLOCK_TYPES


def group_table_blocks_into_rows(
    blocks: list[OcrBlock],
    y_tolerance_norm: int = _DEFAULT_Y_TOLERANCE,
) -> list[list[OcrBlock]]:
    """표 블록을 Y좌표 근접성으로 행(row) 단위로 그룹화한다.

    y_tolerance_norm 파라미터를 통해 외부에서 허용 오차를 주입할 수 있어
    격자 데이터 기반 적응형 허용 오차와 호환된다.

    Args:
        blocks: 표 관련 OCR 블록 목록 (table_header / table_cell / table_row)
        y_tolerance_norm: 같은 행으로 묶을 Y좌표 허용 오차 (정규화 좌표 기준)

    Returns:
        행 단위로 그룹화된 블록 목록의 목록
    """
    if not blocks:
        return []

    # Y 중심값 기준으로 정렬한다
    sorted_blocks = sorted(
        blocks, key=lambda b: (b.bbox_norm[1] + b.bbox_norm[3]) // 2
    )

    rows: list[list[OcrBlock]] = []
    current_row: list[OcrBlock] = [sorted_blocks[0]]

    for block in sorted_blocks[1:]:
        prev_y = _y_center(current_row[-1])
        curr_y = _y_center(block)

        if abs(curr_y - prev_y) <= y_tolerance_norm:
            current_row.append(block)
        else:
            rows.append(current_row)
            current_row = [block]

    rows.append(current_row)
    return rows


def format_table_row_text(
    row_blocks: list[OcrBlock],
    preserve_empty: bool = False,
) -> str:
    """한 행의 블록들을 X좌표 순으로 정렬하고 탭으로 구분된 텍스트를 반환한다.

    preserve_empty=True이면 빈 텍스트 블록도 포함하여 셀 위치를 보존한다.
    이를 통해 빈 셀이 있는 표의 열 정렬 정확도를 높인다.

    Args:
        row_blocks: 동일 행에 속하는 OCR 블록 목록
        preserve_empty: True이면 빈 셀도 탭 구분자로 포함한다

    Returns:
        탭으로 구분된 셀 텍스트 문자열
    """
    # X 좌측 좌표 기준 정렬로 열 순서를 보장한다
    sorted_row = sorted(row_blocks, key=lambda b: b.bbox_norm[0])

    if preserve_empty:
        # 빈 셀도 빈 문자열로 포함하여 표 구조를 보존한다
        cell_texts = [b.text.strip() for b in sorted_row]
    else:
        # 하위 호환성 유지 — 기존 동작(빈 셀 제거)
        cell_texts = [b.text.strip() for b in sorted_row if b.text.strip()]

    return "\t".join(cell_texts)


def render_cells_at_positions(
    row_blocks: list[OcrBlock],
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """각 셀의 텍스트와 bbox를 개별 위치 정보와 함께 반환한다.

    단일 행 문자열 대신 셀별 (텍스트, bbox_norm) 쌍 목록을 반환하여
    PDF 렌더러가 각 셀을 고유한 위치에 배치할 수 있도록 한다.
    빈 텍스트 셀도 포함하여 열 구조를 유지한다.

    Args:
        row_blocks: 동일 행에 속하는 OCR 블록 목록

    Returns:
        (텍스트, bbox_norm) 튜플의 목록 (X 좌표 오름차순 정렬)
    """
    sorted_row = sorted(row_blocks, key=lambda b: b.bbox_norm[0])
    return [(b.text.strip(), b.bbox_norm) for b in sorted_row]


def _y_center(block: OcrBlock) -> int:
    """블록의 Y 중심 좌표를 반환한다."""
    return (block.bbox_norm[1] + block.bbox_norm[3]) // 2
