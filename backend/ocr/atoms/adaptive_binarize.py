from __future__ import annotations

# 적응형 이진화 원자적 모듈
# 컬러/회색 배경의 표 셀을 포함한 이미지를 안정적으로 이진화한다
# Otsu 이진화를 1차 시도하고, 전경 픽셀 비율이 높으면 적응형 가우시안으로 폴백한다

import cv2
import numpy as np

# Otsu 이진화 후 전경 비율이 이 임계값을 초과하면 적응형 방식으로 전환한다
# 40% 초과는 배경/전경 반전 또는 표 셀 음영 채움으로 인한 과도한 픽셀 활성화를 의미한다
_FOREGROUND_RATIO_THRESHOLD: float = 0.40

# 적응형 가우시안 이진화 파라미터
_ADAPTIVE_BLOCK_SIZE: int = 15  # 지역 픽셀 블록 크기 (홀수여야 함)
_ADAPTIVE_C: int = 2            # 평균에서 차감하는 상수


def adaptive_binarize_for_lines(gray: np.ndarray) -> np.ndarray:
    """그레이스케일 이미지에 적응형 이진화를 적용하여 이진 마스크를 반환한다.

    1차: Otsu 이진화로 전역 임계값을 계산한다.
    전경 픽셀 비율이 40%를 초과하면 컬러/회색 셀 배경으로 판단하고
    2차: 적응형 가우시안 이진화로 폴백하여 선을 더 정확히 추출한다.

    Args:
        gray: 그레이스케일 이미지 배열 (uint8, shape: H x W)

    Returns:
        이진 마스크 배열 (0 또는 255, shape: H x W)
    """
    # 1차: Otsu 이진화 (역전 — 선이 전경이 되도록)
    _, binary_otsu = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    # 전경 픽셀(255) 비율 계산
    total_pixels = gray.shape[0] * gray.shape[1]
    foreground_count = int(np.count_nonzero(binary_otsu))
    foreground_ratio = foreground_count / total_pixels if total_pixels > 0 else 0.0

    # 전경 비율이 임계값 이하면 Otsu 결과를 그대로 사용한다
    if foreground_ratio <= _FOREGROUND_RATIO_THRESHOLD:
        return binary_otsu

    # 2차: 적응형 가우시안 이진화로 폴백한다
    # blockSize는 홀수여야 하므로 상수로 보장된 값을 사용한다
    binary_adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        _ADAPTIVE_BLOCK_SIZE,
        _ADAPTIVE_C,
    )
    return binary_adaptive
