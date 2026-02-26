from __future__ import annotations

# 경량 표 사전 감지 원자적 모듈
# OCR 실행 전에 이미지를 축소하여 표 존재 여부를 빠르게 판단한다
# 목표 실행 시간: 20ms 이하

import cv2
import numpy as np
from PIL import Image

# 이미지 다운스케일 비율 — 1/4 크기로 축소한다
_DOWNSCALE_FACTOR: float = 0.25

# 표로 인정할 최소 수평/수직 선 수
_MIN_H_LINES: int = 2
_MIN_V_LINES: int = 2


def quick_table_check(image: Image.Image) -> bool:
    """이미지를 축소하여 표 존재 여부를 빠르게 판단한다.

    이미지를 1/4 크기로 다운스케일한 후 형태학적 연산으로
    수평선과 수직선을 감지한다.
    수평선 2개 이상 AND 수직선 2개 이상이 존재하면 표가 있다고 판정한다.

    Args:
        image: 원본 PIL Image 객체

    Returns:
        표가 감지되면 True, 없으면 False
    """
    try:
        small = _downscale_image(image)
        gray = _to_gray(small)
        binary = _binarize(gray)

        h_count = _count_h_lines(binary)
        v_count = _count_v_lines(binary)

        return h_count >= _MIN_H_LINES and v_count >= _MIN_V_LINES
    except Exception:
        # 감지 실패는 파이프라인을 중단시키지 않는다
        return False


def _downscale_image(image: Image.Image) -> np.ndarray:
    """PIL 이미지를 1/4 크기 BGR numpy 배열로 변환한다."""
    orig_w, orig_h = image.size
    new_w = max(1, int(orig_w * _DOWNSCALE_FACTOR))
    new_h = max(1, int(orig_h * _DOWNSCALE_FACTOR))
    small_pil = image.resize((new_w, new_h), Image.NEAREST)
    rgb = np.array(small_pil.convert("RGB"))
    # PIL RGB → OpenCV BGR 변환
    return rgb[:, :, ::-1].copy()


def _to_gray(bgr: np.ndarray) -> np.ndarray:
    """BGR 배열을 그레이스케일로 변환한다."""
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu 이진화로 이진 마스크를 생성한다."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def _count_h_lines(binary: np.ndarray) -> int:
    """형태학적 연산으로 수평선 수를 세어 반환한다."""
    height, width = binary.shape
    kernel_w = max(1, width // 20)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 1))
    h_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    # 각 행의 최대값이 0이 아니면 수평선 존재로 판정한다
    row_has_line = np.any(h_mask > 0, axis=1)
    transitions = np.diff(row_has_line.astype(np.int8), prepend=0)
    return int(np.sum(transitions > 0))


def _count_v_lines(binary: np.ndarray) -> int:
    """형태학적 연산으로 수직선 수를 세어 반환한다."""
    height, width = binary.shape
    kernel_h = max(1, height // 20)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_h))
    v_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    # 각 열의 최대값이 0이 아니면 수직선 존재로 판정한다
    col_has_line = np.any(v_mask > 0, axis=0)
    transitions = np.diff(col_has_line.astype(np.int8), prepend=0)
    return int(np.sum(transitions > 0))
