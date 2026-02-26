from __future__ import annotations

# 표 격자 구조 유효성 검증 원자적 모듈
# 감지된 수평/수직 선 위치가 유효한 격자를 형성하는지 검증한다
# 최소 행/열 수 조건을 충족해야 True를 반환한다


def validate_grid_structure(
    h_positions: list[int],
    v_positions: list[int],
    min_rows: int = 1,
    min_cols: int = 1,
) -> bool:
    """수평/수직 선 위치 목록이 유효한 격자 구조를 형성하는지 검증한다.

    min_rows개의 행을 형성하려면 (min_rows + 1)개의 수평선이 필요하고,
    min_cols개의 열을 형성하려면 (min_cols + 1)개의 수직선이 필요하다.
    두 조건을 모두 충족해야 유효한 표 격자로 판정한다.

    Args:
        h_positions: 수평 선의 y 픽셀 위치 목록 (정렬된 상태)
        v_positions: 수직 선의 x 픽셀 위치 목록 (정렬된 상태)
        min_rows: 인정할 최소 행 수 (기본값: 1)
        min_cols: 인정할 최소 열 수 (기본값: 1)

    Returns:
        유효한 격자 구조이면 True, 아니면 False
    """
    # min_rows개의 행 = (min_rows + 1)개의 경계선 필요
    required_h_lines = min_rows + 1
    # min_cols개의 열 = (min_cols + 1)개의 경계선 필요
    required_v_lines = min_cols + 1

    has_enough_h = len(h_positions) >= required_h_lines
    has_enough_v = len(v_positions) >= required_v_lines

    return has_enough_h and has_enough_v
