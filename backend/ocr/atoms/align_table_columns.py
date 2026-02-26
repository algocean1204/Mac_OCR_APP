from __future__ import annotations

# 표 열 정렬 원자적 모듈
# 감지된 수직 선 경계를 기반으로 OCR 블록을 열 슬롯에 할당한다
# 빈 셀도 빈 문자열로 보존하여 표 구조의 완전성을 유지한다

from backend.ocr.grounding_parser import OcrBlock


def assign_cells_to_columns(
    row_blocks: list[OcrBlock],
    col_boundaries_norm: list[int],
) -> list[str]:
    """행 내 OCR 블록을 수직 경계선 기반으로 열 슬롯에 할당한다.

    각 블록의 x 중점이 어떤 열 범위 안에 속하는지 판정하고,
    해당 열 슬롯에 텍스트를 배치한다.
    블록이 없는 열 슬롯은 빈 문자열로 유지하여 표 구조를 보존한다.

    Args:
        row_blocks: 동일 행에 속하는 OCR 블록 목록
        col_boundaries_norm: 열 경계 x 좌표 목록 (정규화 0~999, 최소 2개 필요)

    Returns:
        열 순서대로 정렬된 셀 텍스트 목록 (빈 셀은 빈 문자열)
        열 경계가 부족하면 단순 정렬 텍스트 목록을 반환한다
    """
    # 열 경계가 최소 2개(시작+끝) 없으면 열 구조를 판정할 수 없다
    if len(col_boundaries_norm) < 2:
        return [b.text.strip() for b in sorted(row_blocks, key=lambda b: b.bbox_norm[0])]

    num_cols = len(col_boundaries_norm) - 1
    # 각 열 슬롯을 빈 문자열로 초기화한다 (빈 셀 보존을 위해)
    col_slots: list[str] = [""] * num_cols

    for block in row_blocks:
        x1, _, x2, _ = block.bbox_norm
        # 블록의 x 중점으로 열 귀속을 결정한다
        x_mid = (x1 + x2) // 2
        col_idx = _find_column_index(x_mid, col_boundaries_norm)
        if col_idx is not None and col_slots[col_idx] == "":
            # 이미 텍스트가 있는 슬롯에는 덮어쓰지 않는다
            col_slots[col_idx] = block.text.strip()

    return col_slots


def _find_column_index(
    x_mid: int,
    col_boundaries_norm: list[int],
) -> int | None:
    """x 중점이 속하는 열 인덱스를 반환한다.

    Args:
        x_mid: 블록의 x 중점 (정규화 좌표)
        col_boundaries_norm: 열 경계 x 좌표 목록 (오름차순 정렬)

    Returns:
        열 인덱스 (0-based), 어느 열에도 속하지 않으면 None
    """
    for i in range(len(col_boundaries_norm) - 1):
        left = col_boundaries_norm[i]
        right = col_boundaries_norm[i + 1]
        if left <= x_mid < right:
            return i
    return None
