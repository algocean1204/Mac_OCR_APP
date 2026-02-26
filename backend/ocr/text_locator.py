# 텍스트 위치 탐지 모듈
# PIL과 numpy만 사용하여 PDF 페이지 이미지에서 텍스트 영역의
# 바운딩 박스를 픽셀 좌표로 추출한다.
# 외부 OCR 라이브러리 없이 수평/수직 투영 프로파일 기법을 사용한다.
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageFilter


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------

@dataclass
class TextRegion:
    """이미지 픽셀 좌표계에서 텍스트 블록의 바운딩 박스를 나타낸다."""
    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min


# ---------------------------------------------------------------------------
# 내부 알고리즘 헬퍼
# ---------------------------------------------------------------------------

def _to_binary(image: Image.Image, threshold_ratio: float) -> np.ndarray:
    """이미지를 그레이스케일로 변환 후 임계값 이진화를 수행한다.

    밝은 배경에 어두운 텍스트를 가정한다.
    threshold_ratio: 전체 픽셀 최대값 대비 임계값 비율 (0~1).
    반환값은 어두운 픽셀이 1, 밝은 픽셀이 0인 uint8 배열이다.
    """
    # 그레이스케일 변환 후 미세 노이즈를 줄이는 가우시안 블러 적용
    gray = image.convert("L").filter(ImageFilter.GaussianBlur(radius=1))
    arr = np.array(gray, dtype=np.float32)

    # Otsu 방식 근사: 히스토그램 기반 최적 임계값을 계산한다
    counts, bin_edges = np.histogram(arr.ravel(), bins=256, range=(0, 256))
    total = arr.size
    best_thresh = 128.0
    max_var = 0.0
    w0 = 0.0
    sum_total = float(np.sum(np.arange(256) * counts))
    sum0 = 0.0

    for t in range(256):
        w0 += counts[t]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        sum0 += t * counts[t]
        mu0 = sum0 / w0
        mu1 = (sum_total - sum0) / w1
        var = w0 * w1 * (mu0 - mu1) ** 2
        if var > max_var:
            max_var = var
            best_thresh = bin_edges[t + 1]

    # 임계값보다 어두운 픽셀을 1로 표시한다 (텍스트 픽셀 = 1)
    binary: np.ndarray = (arr < best_thresh * threshold_ratio).astype(np.uint8)
    return binary


def _horizontal_projection(binary: np.ndarray) -> np.ndarray:
    """행 방향(수평) 투영 프로파일을 계산한다.

    각 행의 어두운 픽셀 수(텍스트 픽셀 합계)를 반환한다.
    """
    return binary.sum(axis=1).astype(np.int32)


def _vertical_projection(binary: np.ndarray) -> np.ndarray:
    """열 방향(수직) 투영 프로파일을 계산한다.

    각 열의 어두운 픽셀 수를 반환한다.
    """
    return binary.sum(axis=0).astype(np.int32)


def _find_bands(
    profile: np.ndarray,
    min_density: int,
    min_size: int,
    merge_gap: int,
) -> list[tuple[int, int]]:
    """프로파일에서 임계값 이상인 연속 구간(밴드)을 찾는다.

    min_density: 밴드로 인정하는 최소 픽셀 밀도.
    min_size: 최소 밴드 길이(픽셀).
    merge_gap: 이 픽셀 이하로 인접한 밴드는 하나로 병합한다.
    반환값: (시작, 끝) 인덱스 리스트 (끝 인덱스는 포함).
    """
    active = profile >= min_density
    bands: list[tuple[int, int]] = []
    start: int | None = None

    for i, is_active in enumerate(active):
        if is_active and start is None:
            start = i
        elif not is_active and start is not None:
            if i - start >= min_size:
                bands.append((start, i - 1))
            start = None

    # 마지막 구간 처리
    if start is not None and len(profile) - start >= min_size:
        bands.append((start, len(profile) - 1))

    # 근접 밴드 병합
    merged: list[tuple[int, int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(list(band))  # type: ignore[arg-type]

    return [(s, e) for s, e in merged]  # type: ignore[misc]


def _find_column_segments(
    binary_strip: np.ndarray,
    min_col_width: int,
    col_merge_gap: int,
) -> list[tuple[int, int]]:
    """텍스트 행 밴드 내에서 수직 투영으로 열 세그먼트를 찾는다.

    multi-column 레이아웃에서 각 컬럼의 X 범위를 반환한다.
    """
    v_proj = _vertical_projection(binary_strip)
    # 열 밀도 임계값: 최대값의 5% 이상인 열을 텍스트 열로 간주
    min_col_density = max(1, int(v_proj.max() * 0.05)) if v_proj.max() > 0 else 1
    segments = _find_bands(v_proj, min_col_density, min_col_width, col_merge_gap)
    return segments


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def detect_text_regions(
    image: Image.Image,
    min_line_height: int = 6,
    merge_gap: int = 8,
    threshold_ratio: float = 1.05,
    min_col_width: int = 20,
    col_merge_gap: int = 30,
) -> list[TextRegion]:
    """PIL 이미지에서 텍스트 영역의 바운딩 박스 목록을 반환한다.

    Args:
        image: 200 DPI로 렌더링된 PDF 페이지 PIL 이미지.
        min_line_height: 텍스트 행으로 인정하는 최소 픽셀 높이.
        merge_gap: 이 픽셀 이하 간격의 행 밴드는 하나로 병합한다.
        threshold_ratio: Otsu 임계값에 곱할 비율 (1.0 = Otsu 그대로).
        min_col_width: 텍스트 컬럼으로 인정하는 최소 픽셀 폭.
        col_merge_gap: 이 픽셀 이하 간격의 컬럼 세그먼트는 병합한다.

    Returns:
        TextRegion 리스트 (위에서 아래, 왼쪽에서 오른쪽 순).
    """
    img_w, img_h = image.size
    binary = _to_binary(image, threshold_ratio)

    # 1단계: 수평 투영으로 텍스트 행 밴드 탐지
    h_proj = _horizontal_projection(binary)
    # 행 밀도 임계값: 이미지 폭의 0.3% 이상 어두운 픽셀이 있는 행을 텍스트 행으로 본다
    min_row_density = max(1, int(img_w * 0.003))
    row_bands = _find_bands(h_proj, min_row_density, min_line_height, merge_gap)

    regions: list[TextRegion] = []

    for y_start, y_end in row_bands:
        # 2단계: 각 행 밴드 내에서 수직 투영으로 컬럼 세그먼트 탐지
        strip = binary[y_start : y_end + 1, :]
        col_segs = _find_column_segments(strip, min_col_width, col_merge_gap)

        if not col_segs:
            # 컬럼 세그먼트가 없으면 행 전체를 하나의 영역으로 처리
            regions.append(TextRegion(
                x_min=0, y_min=y_start, x_max=img_w - 1, y_max=y_end
            ))
        else:
            for x_start, x_end in col_segs:
                regions.append(TextRegion(
                    x_min=x_start, y_min=y_start,
                    x_max=x_end, y_max=y_end,
                ))

    # 위→아래, 왼쪽→오른쪽 순으로 정렬한다
    regions.sort(key=lambda r: (r.y_min, r.x_min))
    return regions


def map_text_to_regions(
    text_lines: list[str],
    regions: list[TextRegion],
) -> list[tuple[str, TextRegion]]:
    """VLM이 추출한 텍스트 줄 목록을 탐지된 텍스트 영역에 매핑한다.

    텍스트 줄 수(N)와 탐지 영역 수(M)가 다를 수 있으므로
    높이 비례 배분 방식으로 각 텍스트 줄을 가장 적합한 영역에 할당한다.

    Args:
        text_lines: VLM OCR 결과의 텍스트 줄 목록.
        regions: detect_text_regions()가 반환한 TextRegion 목록.

    Returns:
        (텍스트_줄, TextRegion) 튜플 목록.
    """
    if not regions:
        return []

    if not text_lines:
        return []

    # 영역이 하나뿐이거나 텍스트 줄이 하나뿐인 경우 단순 처리
    if len(regions) == 1:
        return [(line, regions[0]) for line in text_lines]

    # 각 텍스트 줄의 인덱스를 0~1 정규화 범위로 계산한 뒤
    # 전체 이미지 높이 내 영역들의 Y 위치와 매핑한다
    n = len(text_lines)
    m = len(regions)

    # 각 영역의 Y 중심값을 계산하여 정렬된 순서를 기준으로 삼는다
    sorted_regions = sorted(regions, key=lambda r: (r.y_min, r.x_min))

    result: list[tuple[str, TextRegion]] = []
    for i, line in enumerate(text_lines):
        # 텍스트 줄 인덱스를 영역 인덱스로 선형 매핑한다
        region_idx = min(int(i * m / n), m - 1)
        result.append((line, sorted_regions[region_idx]))

    return result
