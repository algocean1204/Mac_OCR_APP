from __future__ import annotations

# 행 그룹화 Y 허용 오차 계산 원자적 모듈
# 감지된 수평 격자선 간격을 기반으로 행 그룹화에 사용할 Y 허용 오차를 동적으로 계산한다
# 정규화 좌표(0~999) 기준으로 반환한다

import statistics


def compute_adaptive_y_tolerance(
    h_line_positions_px: list[int],
    page_height_px: int,
    default_tolerance: int = 15,
) -> int:
    """감지된 수평 선 위치로부터 적응형 Y 허용 오차를 계산한다.

    인접한 수평선 간 간격의 중앙값을 구하고,
    픽셀 좌표를 정규화 좌표(0~999)로 변환한 후 절반을 허용 오차로 반환한다.
    선 위치가 충분하지 않으면 기본값을 반환한다.

    Args:
        h_line_positions_px: 수평 선의 y 픽셀 위치 목록 (정렬된 상태)
        page_height_px: 페이지(이미지) 전체 높이 (픽셀)
        default_tolerance: 데이터가 부족할 때 반환할 기본 허용 오차 (정규화 좌표)

    Returns:
        행 그룹화에 사용할 Y 허용 오차 (정규화 좌표 0~999 기준)
    """
    # 간격 계산을 위해 최소 2개의 선 위치가 필요하다
    if len(h_line_positions_px) < 2 or page_height_px <= 0:
        return default_tolerance

    # 인접 수평선 간 픽셀 간격을 계산한다
    gaps_px = [
        h_line_positions_px[i + 1] - h_line_positions_px[i]
        for i in range(len(h_line_positions_px) - 1)
        if h_line_positions_px[i + 1] > h_line_positions_px[i]
    ]

    if not gaps_px:
        return default_tolerance

    # 간격의 중앙값을 정규화 좌표로 변환한다
    median_gap_px = statistics.median(gaps_px)
    median_gap_norm = (median_gap_px / page_height_px) * 999

    # 중앙값 간격의 절반을 허용 오차로 사용하며 최소 1을 보장한다
    tolerance = max(1, int(median_gap_norm / 2))
    return tolerance
