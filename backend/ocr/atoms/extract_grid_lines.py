from __future__ import annotations

# 격자 선 위치 추출 원자적 모듈
# 이진 형태학적 마스크에서 수평/수직 선의 픽셀 위치를 추출한다
# 행 투영 또는 열 투영을 기반으로 전환 엣지를 탐색한다

import numpy as np


# 선 존재 판정 임계값 — 이미지 너비(또는 높이) 대비 점유 비율
_LINE_PRESENCE_THRESHOLD: float = 0.10


def extract_h_line_positions(h_lines_mask: np.ndarray) -> list[int]:
    """수평 선 마스크에서 선이 존재하는 y 픽셀 좌표 목록을 추출한다.

    각 행(row)의 픽셀 합산으로 행 투영을 만들고,
    이미지 너비 대비 10% 이상 점유된 행을 선으로 판정한다.
    연속된 선 구간의 시작 지점(전환 엣지)을 반환한다.

    Args:
        h_lines_mask: 수평 선만 포함한 이진 마스크 (0 또는 255)

    Returns:
        선이 시작되는 y 픽셀 위치의 정렬된 목록
    """
    if h_lines_mask.size == 0:
        return []

    height, width = h_lines_mask.shape
    # 각 행의 비-영 픽셀 수를 합산하여 행 투영을 생성한다
    row_projection = np.sum(h_lines_mask > 0, axis=1)
    threshold_px = width * _LINE_PRESENCE_THRESHOLD
    # 임계값 이상이면 해당 행에 수평선이 존재한다고 판정한다
    line_present = (row_projection >= threshold_px).astype(np.int8)

    # 0→1 전환 지점이 선의 시작 y 좌표다
    transitions = np.diff(line_present, prepend=0)
    y_positions = [int(y) for y in np.where(transitions > 0)[0]]
    return sorted(y_positions)


def extract_v_line_positions(v_lines_mask: np.ndarray) -> list[int]:
    """수직 선 마스크에서 선이 존재하는 x 픽셀 좌표 목록을 추출한다.

    각 열(column)의 픽셀 합산으로 열 투영을 만들고,
    이미지 높이 대비 10% 이상 점유된 열을 선으로 판정한다.
    연속된 선 구간의 시작 지점(전환 엣지)을 반환한다.

    Args:
        v_lines_mask: 수직 선만 포함한 이진 마스크 (0 또는 255)

    Returns:
        선이 시작되는 x 픽셀 위치의 정렬된 목록
    """
    if v_lines_mask.size == 0:
        return []

    height, width = v_lines_mask.shape
    # 각 열의 비-영 픽셀 수를 합산하여 열 투영을 생성한다
    col_projection = np.sum(v_lines_mask > 0, axis=0)
    threshold_px = height * _LINE_PRESENCE_THRESHOLD
    # 임계값 이상이면 해당 열에 수직선이 존재한다고 판정한다
    line_present = (col_projection >= threshold_px).astype(np.int8)

    # 0→1 전환 지점이 선의 시작 x 좌표다
    transitions = np.diff(line_present, prepend=0)
    x_positions = [int(x) for x in np.where(transitions > 0)[0]]
    return sorted(x_positions)
