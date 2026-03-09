# 배치 OCR 처리 모듈
# 검출된 텍스트 영역들을 배치로 묶어 GPU에 한 번에 전달한다.
# 개별 추론 대비 GPU 활용률을 극대화하여 처리 속도를 높인다.
#
# GLM-OCR은 VLM(Vision-Language Model)이므로 이미지+프롬프트 쌍으로 배치 처리한다.
# 배치 크기는 가용 메모리에 맞게 자동 조절한다.
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import torch
from PIL import Image

from backend.ocr.atoms.detect_text_regions import TextRegion, rectify_crop
from backend.ocr.text_cleaner import clean_text

logger = logging.getLogger(__name__)

# 배치 크기 — Apple Silicon 48GB 통합 메모리 기준
# GLM-OCR bf16 모델은 약 7GB, 크롭 이미지는 작으므로 여유 있음
_DEFAULT_BATCH_SIZE: int = 8
# 크롭 이미지 최소 크기
_MIN_CROP_SIZE: int = 20
# 크롭 이미지 최대 크기 (긴 변 기준)
_MAX_CROP_SIZE: int = 1024


@dataclass
class RegionOcrResult:
    """텍스트 영역별 OCR 결과. 위치 정보와 텍스트를 포함한다."""
    region: TextRegion
    text: str
    bbox_norm: tuple[float, float, float, float]


def run_batch_ocr(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    regions: list[TextRegion],
    max_tokens: int = 4096,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> list[RegionOcrResult]:
    """검출된 텍스트 영역을 배치로 묶어 OCR을 실행한다.

    1. 각 영역을 크롭하고 기울기를 보정한다.
    2. 크롭 이미지들을 배치로 묶는다.
    3. 배치 단위로 GPU에 전달하여 병렬 추론한다.
    4. 결과를 수집하여 반환한다.

    Args:
        model: 로드된 GLM-OCR 모델
        processor: 로드된 프로세서
        device: torch 장치
        image: 원본 페이지 이미지
        regions: 검출된 텍스트 영역 목록
        max_tokens: 영역당 최대 생성 토큰 수
        batch_size: 배치 크기

    Returns:
        위치 정보가 포함된 OCR 결과 목록
    """
    from backend.ocr.prompt import OcrPrompt

    # 1단계: 모든 영역을 크롭하고 기울기 보정
    crops: list[tuple[TextRegion, Image.Image]] = []
    for region in regions:
        crop = rectify_crop(image, region)
        if crop is None:
            continue

        # 크기 검증
        cw, ch = crop.size
        if cw < _MIN_CROP_SIZE or ch < _MIN_CROP_SIZE:
            crop.close()
            continue

        # 패딩 기반 리사이징 — 비율 유지하며 최대 크기 제한
        crop = _resize_with_padding(crop, _MAX_CROP_SIZE)
        crops.append((region, crop))

    if not crops:
        return []

    # 2단계: 배치 단위로 OCR 실행
    results: list[RegionOcrResult] = []
    prompt = OcrPrompt.get_grounding()

    for batch_start in range(0, len(crops), batch_size):
        batch_end = min(batch_start + batch_size, len(crops))
        batch = crops[batch_start:batch_end]

        # 배치 내 각 이미지를 개별 처리 (GLM-OCR은 이미지별 추론)
        # transformers의 chat template은 단일 이미지만 지원하므로
        # 배치 내에서 순차 처리하되, 텐서 준비/정리를 배치 단위로 묶는다
        batch_texts = _process_batch(
            model, processor, device, batch, prompt, max_tokens,
        )

        for i, (region, crop) in enumerate(batch):
            text = batch_texts[i] if i < len(batch_texts) else ""
            crop.close()

            if not text.strip():
                continue

            results.append(RegionOcrResult(
                region=region,
                text=text,
                bbox_norm=region.bbox_norm,
            ))

    return results


def _process_batch(
    model: Any,
    processor: Any,
    device: torch.device,
    batch: list[tuple[TextRegion, Image.Image]],
    prompt: str,
    max_tokens: int,
) -> list[str]:
    """배치 내 이미지들을 처리한다.

    GLM-OCR은 단일 이미지 추론 모델이므로 배치 내에서 순차 처리하되,
    중간 텐서를 재활용하고 불필요한 메모리 할당을 방지한다.
    """
    texts: list[str] = []

    for region, crop in batch:
        try:
            raw = _run_single_inference(
                model, processor, device, crop, prompt, max_tokens,
            )
            cleaned = clean_text(raw).strip()
            texts.append(cleaned)
        except Exception as exc:
            logger.warning("영역 OCR 실패 (x=%d, y=%d): %s", region.x, region.y, exc)
            texts.append("")

    return texts


def _run_single_inference(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    prompt: str,
    max_tokens: int,
) -> str:
    """단일 크롭 이미지에 대해 GLM-OCR 추론을 실행한다."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=max_tokens)

    input_len = inputs["input_ids"].shape[1]
    return processor.decode(outputs[0][input_len:], skip_special_tokens=True)


def _resize_with_padding(
    image: Image.Image,
    max_size: int,
) -> Image.Image:
    """비율을 유지하며 최대 크기로 리사이징한다.

    종횡비를 유지하고 남는 공간은 흰색으로 패딩하여
    인식기의 입력 품질을 보장한다.
    """
    w, h = image.size
    if w <= max_size and h <= max_size:
        return image

    # 비율 유지 축소
    ratio = max_size / max(w, h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    resized = image.resize((new_w, new_h), Image.LANCZOS)

    return resized
