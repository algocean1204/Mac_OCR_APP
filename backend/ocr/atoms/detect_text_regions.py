# CRAFT 기반 고급 텍스트 영역 검출 모듈
# Tesseract 대신 CRAFT(Character Region Awareness for Text) 딥러닝 모델을 사용하여
# 픽셀 수준의 정교한 텍스트 영역을 검출한다.
# 기울어진 텍스트를 보정(Rectification)하고 정확한 바운딩 박스를 생성한다.
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# CRAFT 모델 인스턴스 — 프로세스 당 한 번만 로드
_craft_instance: object | None = None


@dataclass
class TextRegion:
    """검출된 텍스트 영역. OCR 입력 단위가 된다."""
    # 픽셀 좌표 (원본 이미지 기준)
    x: int
    y: int
    x2: int
    y2: int
    # 정규화 좌표 (0~1, PDF 좌표 변환용)
    bbox_norm: tuple[float, float, float, float]
    # 회전 각도 (도, 기울기 보정에 사용)
    angle: float
    # 신뢰도 (0~1)
    confidence: float
    # 검출된 폴리곤 꼭짓점 (기울기 정보 포함)
    polygon: np.ndarray | None = None


def detect_text_regions(
    image: Image.Image,
    text_threshold: float = 0.5,
    link_threshold: float = 0.3,
    low_text: float = 0.3,
) -> list[TextRegion]:
    """CRAFT로 이미지에서 텍스트 영역을 검출한다.

    CRAFT는 글자 중심의 Heatmap을 생성하여 픽셀 단위로
    텍스트 영역을 폴리곤 형태로 정교하게 검출한다.

    Args:
        image: 원본 페이지 이미지
        text_threshold: 텍스트 영역 신뢰도 임계값
        link_threshold: 글자 간 연결 임계값
        low_text: 낮은 텍스트 영역 임계값

    Returns:
        검출된 텍스트 영역 목록 (읽기 순서로 정렬)
    """
    img_w, img_h = image.size

    # PIL → numpy 변환
    img_array = np.array(image)
    if len(img_array.shape) == 2:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_GRAY2RGB)
    elif img_array.shape[2] == 4:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)

    # CRAFT 텍스트 검출 실행
    boxes, polys = _run_craft_detection(
        img_array, text_threshold, link_threshold, low_text,
    )

    if boxes is None or len(boxes) == 0:
        # CRAFT 실패 시 Tesseract 폴백
        logger.info("CRAFT 검출 실패 — Tesseract 폴백")
        return _fallback_tesseract(image, img_w, img_h)

    # 폴리곤 → TextRegion 변환
    regions: list[TextRegion] = []
    for i, poly in enumerate(polys):
        if poly is None:
            poly = boxes[i]

        # 폴리곤에서 축 정렬 바운딩 박스와 기울기 추출
        x, y, x2, y2, angle = _polygon_to_bbox_with_angle(poly)

        # 너무 작은 영역 필터링
        bw = x2 - x
        bh = y2 - y
        if bw < img_w * 0.005 or bh < img_h * 0.003:
            continue

        # bbox 패딩 — 글자 가장자리 잘림 방지
        # 글자 높이의 10%를 상하좌우에 추가한다
        pad = max(2, int(bh * 0.1))
        x = max(0, x - pad)
        y = max(0, y - pad)
        x2 = min(img_w, x2 + pad)
        y2 = min(img_h, y2 + pad)

        # 정규화 좌표 계산
        bbox_norm = (
            max(0, x / img_w),
            max(0, y / img_h),
            min(1, x2 / img_w),
            min(1, y2 / img_h),
        )

        regions.append(TextRegion(
            x=int(x), y=int(y), x2=int(x2), y2=int(y2),
            bbox_norm=bbox_norm,
            angle=angle,
            confidence=1.0,  # CRAFT는 신뢰도를 별도 제공하지 않음
            polygon=poly,
        ))

    # Y 위치 → X 위치 순으로 정렬 (읽기 순서)
    regions.sort(key=lambda r: (r.y, r.x))
    logger.info("CRAFT 검출: %d개 텍스트 영역", len(regions))
    return regions


def _run_craft_detection(
    img_array: np.ndarray,
    text_threshold: float,
    link_threshold: float,
    low_text: float,
) -> tuple[np.ndarray | None, list]:
    """CRAFT 모델로 텍스트 검출을 실행한다."""
    global _craft_instance

    try:
        from craft_text_detector import Craft

        if _craft_instance is None:
            _craft_instance = Craft(
                output_dir=None,
                crop_type="box",
                cuda=False,  # MPS는 Craft 내부에서 미지원, CPU 사용
                text_threshold=text_threshold,
                link_threshold=link_threshold,
                low_text=low_text,
            )

        prediction = _craft_instance.detect_text(img_array)
        boxes = prediction["boxes"]
        polys = prediction["polys"]
        return boxes, polys

    except Exception as exc:
        logger.warning("CRAFT 검출 오류: %s", exc)
        return None, []


def _polygon_to_bbox_with_angle(
    poly: np.ndarray,
) -> tuple[int, int, int, int, float]:
    """폴리곤에서 축 정렬 바운딩 박스와 기울기 각도를 추출한다.

    OpenCV minAreaRect를 사용하여 최소 면적 회전 사각형을 구한 뒤,
    축 정렬 바운딩 박스와 기울기를 반환한다.
    """
    pts = poly.astype(np.float32)

    # 최소 면적 회전 사각형으로 기울기 감지
    rect = cv2.minAreaRect(pts)
    angle = rect[2]

    # 각도 보정 (-90~0 → -45~45 범위로 변환)
    if angle < -45:
        angle = angle + 90

    # 축 정렬 바운딩 박스
    x = int(np.min(pts[:, 0]))
    y = int(np.min(pts[:, 1]))
    x2 = int(np.max(pts[:, 0]))
    y2 = int(np.max(pts[:, 1]))

    return x, y, x2, y2, angle


def rectify_crop(
    image: Image.Image,
    region: TextRegion,
    padding_ratio: float = 0.15,
) -> Image.Image | None:
    """텍스트 영역을 크롭하고 기울기를 보정한다.

    STN/TPS 대신 OpenCV의 affine transform을 사용하여
    기울어진 텍스트를 반듯하게 펴준다.

    Args:
        image: 원본 이미지
        region: 검출된 텍스트 영역
        padding_ratio: 글자 잘림 방지 패딩 비율

    Returns:
        기울기 보정된 크롭 이미지, 또는 None (크롭 실패 시)
    """
    img_w, img_h = image.size
    img_array = np.array(image)

    # 패딩 포함 크롭 영역 계산
    bh = region.y2 - region.y
    pad = int(bh * padding_ratio)

    x1 = max(0, region.x - pad)
    y1 = max(0, region.y - pad)
    x2 = min(img_w, region.x2 + pad)
    y2 = min(img_h, region.y2 + pad)

    crop_w = x2 - x1
    crop_h = y2 - y1
    if crop_w < 10 or crop_h < 10:
        return None

    cropped = img_array[y1:y2, x1:x2]

    # 기울기가 2도 이상이면 보정
    if abs(region.angle) >= 2.0:
        cropped = _deskew(cropped, region.angle)

    return Image.fromarray(cropped)


def _deskew(img: np.ndarray, angle: float) -> np.ndarray:
    """이미지를 지정된 각도만큼 회전하여 기울기를 보정한다."""
    h, w = img.shape[:2]
    center = (w / 2, h / 2)

    # 회전 행렬 생성 (기울기를 0도로 만듦)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    # 회전 후 이미지 크기 계산 (잘림 방지)
    cos_val = abs(rotation_matrix[0, 0])
    sin_val = abs(rotation_matrix[0, 1])
    new_w = int(h * sin_val + w * cos_val)
    new_h = int(h * cos_val + w * sin_val)

    rotation_matrix[0, 2] += (new_w - w) / 2
    rotation_matrix[1, 2] += (new_h - h) / 2

    rotated = cv2.warpAffine(
        img, rotation_matrix, (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def _fallback_tesseract(
    image: Image.Image,
    img_w: int,
    img_h: int,
) -> list[TextRegion]:
    """CRAFT 실패 시 Tesseract 기반 텍스트 영역 검출로 폴백한다."""
    try:
        import pytesseract
    except ImportError:
        return []

    try:
        data = pytesseract.image_to_data(
            image, lang="kor+eng", config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return []

    # 단어 → 행 그룹화 → TextRegion 변환
    words: list[dict] = []
    for i in range(len(data["text"])):
        if int(data["conf"][i]) < 10:
            continue
        text = data["text"][i].strip()
        if not text:
            continue
        words.append({
            "x": data["left"][i],
            "y": data["top"][i],
            "x2": data["left"][i] + data["width"][i],
            "y2": data["top"][i] + data["height"][i],
        })

    if not words:
        return []

    # 행 그룹화
    words.sort(key=lambda w: (w["y"], w["x"]))
    rows: list[list[dict]] = [[words[0]]]
    for w in words[1:]:
        last = rows[-1]
        cy = sum((r["y"] + r["y2"]) / 2 for r in last) / len(last)
        wcy = (w["y"] + w["y2"]) / 2
        avg_h = sum(r["y2"] - r["y"] for r in last) / len(last)
        if abs(wcy - cy) <= avg_h * 0.6:
            last.append(w)
        else:
            rows.append([w])

    regions: list[TextRegion] = []
    for row in rows:
        x = min(w["x"] for w in row)
        y = min(w["y"] for w in row)
        x2 = max(w["x2"] for w in row)
        y2 = max(w["y2"] for w in row)

        regions.append(TextRegion(
            x=x, y=y, x2=x2, y2=y2,
            bbox_norm=(x / img_w, y / img_h, x2 / img_w, y2 / img_h),
            angle=0.0,
            confidence=0.8,
        ))

    return regions
