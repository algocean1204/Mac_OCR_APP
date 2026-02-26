# 표 영역 감지 모듈
# OpenCV의 수평/수직 직선 감지로 이미지 내 표 영역을 탐지한다
# 감지된 표 영역은 행·열 수 추정 정보와 함께 반환된다
# 적응형 이진화, 격자선 위치 추출, 격자 유효성 검증을 적용한다
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from backend.ocr.atoms.adaptive_binarize import adaptive_binarize_for_lines
from backend.ocr.atoms.extract_grid_lines import (
    extract_h_line_positions,
    extract_v_line_positions,
)
from backend.ocr.atoms.validate_table_grid import validate_grid_structure


@dataclass
class TableRegion:
    """감지된 표 영역을 나타낸다.

    Attributes:
        x: 좌상단 x 좌표 (픽셀)
        y: 좌상단 y 좌표 (픽셀)
        width: 표 너비 (픽셀)
        height: 표 높이 (픽셀)
        rows: 감지된 행 수
        cols: 감지된 열 수
        h_line_positions: 표 영역 내 수평 선의 y 픽셀 좌표 목록
        v_line_positions: 표 영역 내 수직 선의 x 픽셀 좌표 목록
    """

    x: int
    y: int
    width: int
    height: int
    rows: int
    cols: int
    h_line_positions: list[int] = field(default_factory=list)
    v_line_positions: list[int] = field(default_factory=list)


# 표로 인정할 최소 면적 비율 (이미지 전체 면적 대비)
_MIN_AREA_RATIO: float = 0.05

# 허용하는 표의 가로세로 비율 범위
_ASPECT_RATIO_MIN: float = 0.3
_ASPECT_RATIO_MAX: float = 3.0


def detect_table_regions(image_array: np.ndarray) -> list[TableRegion]:
    """이미지에서 표 영역을 수평/수직 직선 감지로 탐지한다.

    적응형 이진화를 사용하여 컬러/회색 셀 배경이 있어도 선을 안정적으로 감지하고,
    격자 유효성 검증으로 실제 표 구조가 아닌 영역을 필터링한다.

    Args:
        image_array: OpenCV BGR 이미지 배열 (numpy ndarray)

    Returns:
        감지된 표 영역 목록 (좌상단→우하단 순)
    """
    gray = _to_grayscale(image_array)
    # Otsu 또는 적응형 가우시안으로 이진화한다 (컬러 셀 배경 처리)
    binary = adaptive_binarize_for_lines(gray)

    h_lines = _extract_horizontal_lines(binary)
    v_lines = _extract_vertical_lines(binary)

    combined = _combine_masks(h_lines, v_lines)
    contours = _find_contours(combined)

    img_area = image_array.shape[0] * image_array.shape[1]
    min_area = img_area * _MIN_AREA_RATIO

    regions: list[TableRegion] = []
    for contour in contours:
        region = _contour_to_region(contour, h_lines, v_lines, min_area)
        if region is not None:
            regions.append(region)

    # 좌상단 기준(y → x 순)으로 정렬하여 반환한다
    regions.sort(key=lambda r: (r.y, r.x))
    return regions


def _to_grayscale(image_array: np.ndarray) -> np.ndarray:
    """BGR 이미지를 그레이스케일로 변환한다."""
    if len(image_array.shape) == 2:
        # 이미 그레이스케일인 경우 그대로 반환한다
        return image_array
    return cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)


def _extract_horizontal_lines(binary: np.ndarray) -> np.ndarray:
    """형태학적 연산으로 수평 직선만 추출한다."""
    height, width = binary.shape
    # 커널 너비를 이미지 너비의 1/30 로 설정한다
    kernel_width = max(1, width // 30)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def _extract_vertical_lines(binary: np.ndarray) -> np.ndarray:
    """형태학적 연산으로 수직 직선만 추출한다."""
    height, width = binary.shape
    # 커널 높이를 이미지 높이의 1/30 로 설정한다
    kernel_height = max(1, height // 30)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_height))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def _combine_masks(
    h_lines: np.ndarray,
    v_lines: np.ndarray,
) -> np.ndarray:
    """수평/수직 직선 마스크를 합쳐 하나의 결합 마스크로 반환한다."""
    return cv2.add(h_lines, v_lines)


def _find_contours(mask: np.ndarray) -> list[np.ndarray]:
    """마스크에서 외곽 윤곽선을 찾아 반환한다."""
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    return list(contours)


def _contour_to_region(
    contour: np.ndarray,
    h_lines: np.ndarray,
    v_lines: np.ndarray,
    min_area: float,
) -> TableRegion | None:
    """단일 윤곽선을 TableRegion으로 변환한다.

    면적, 가로세로 비율 필터 통과 후 격자 유효성 검증을 추가로 수행한다.
    격자 구조가 유효하지 않으면 None을 반환한다.
    유효한 경우 수평/수직 선 위치를 추출하여 TableRegion에 저장한다.
    """
    x, y, w, h = cv2.boundingRect(contour)
    area = w * h

    # 최소 면적 필터
    if area < min_area:
        return None

    # 가로세로 비율 필터
    aspect_ratio = w / h if h > 0 else 0.0
    if not (_ASPECT_RATIO_MIN <= aspect_ratio <= _ASPECT_RATIO_MAX):
        return None

    # ROI(관심 영역) 마스크를 잘라내어 격자 선 위치를 추출한다
    h_roi = h_lines[y : y + h, x : x + w]
    v_roi = v_lines[y : y + h, x : x + w]

    # 로컬 ROI 좌표의 선 위치를 추출하고 전역 픽셀 좌표로 변환한다
    local_h_positions = extract_h_line_positions(h_roi)
    local_v_positions = extract_v_line_positions(v_roi)
    h_positions_global = [py + y for py in local_h_positions]
    v_positions_global = [px + x for px in local_v_positions]

    # 격자 유효성 검증 — 최소 1행 1열 구조가 아니면 표로 인정하지 않는다
    if not validate_grid_structure(local_h_positions, local_v_positions, min_rows=1, min_cols=1):
        return None

    rows = _estimate_row_count(h_lines, x, y, w, h)
    cols = _estimate_col_count(v_lines, x, y, w, h)

    return TableRegion(
        x=x,
        y=y,
        width=w,
        height=h,
        rows=rows,
        cols=cols,
        h_line_positions=h_positions_global,
        v_line_positions=v_positions_global,
    )


def _estimate_row_count(
    h_lines: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> int:
    """표 영역 내 수평 직선 수로 행 수를 추정한다."""
    roi = h_lines[y : y + h, x : x + w]
    # 각 행의 최대값이 0이 아니면 해당 행에 수평선이 존재한다
    row_has_line = np.any(roi > 0, axis=1)
    # 연속 직선 구간을 하나의 선으로 집계한다
    transitions = np.diff(row_has_line.astype(np.int8))
    line_count = int(np.sum(transitions > 0))
    # 직선 수 + 1 = 행 수 (최소 1)
    return max(1, line_count + 1)


def _estimate_col_count(
    v_lines: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> int:
    """표 영역 내 수직 직선 수로 열 수를 추정한다."""
    roi = v_lines[y : y + h, x : x + w]
    # 각 열의 최대값이 0이 아니면 해당 열에 수직선이 존재한다
    col_has_line = np.any(roi > 0, axis=0)
    transitions = np.diff(col_has_line.astype(np.int8))
    line_count = int(np.sum(transitions > 0))
    return max(1, line_count + 1)
