# 블록 단위 OCR 모듈
# 문장 블록별로 이미지를 크롭하여 개별 OCR을 실행한다
# GLM-OCR 모델 인스턴스를 받아서 각 블록을 독립적으로 처리한다
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import torch
from PIL import Image

from backend.ocr.atoms.merge_sentence_blocks import SentenceBlock
from backend.ocr.text_cleaner import clean_text

logger = logging.getLogger(__name__)

# 크롭 시 블록 주변 패딩 비율 (글자 높이 대비)
_PADDING_RATIO: float = 0.3
# 크롭 이미지 최소 크기 (OCR 품질 보장)
_MIN_CROP_SIZE: int = 32


@dataclass
class BlockOcrResult:
    """블록 단위 OCR 결과. 위치 정보와 텍스트를 포함한다."""
    block: SentenceBlock
    text: str
    # 정규화 좌표 (0~1) — PDF 좌표 변환에 사용
    bbox_norm: tuple[float, float, float, float]


def run_block_ocr(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    blocks: list[SentenceBlock],
    max_tokens: int = 4096,
) -> list[BlockOcrResult]:
    """각 블록을 크롭하여 개별 OCR을 실행한다.

    Args:
        model: 로드된 GLM-OCR 모델
        processor: 로드된 프로세서
        device: torch 장치
        image: 원본 페이지 이미지
        blocks: 문장 단위 블록 목록
        max_tokens: 블록당 최대 생성 토큰 수

    Returns:
        위치 정보가 포함된 OCR 결과 목록
    """
    img_w, img_h = image.size
    results: list[BlockOcrResult] = []

    for block in blocks:
        # 1. 블록 영역을 패딩 포함하여 크롭
        crop = _crop_block(image, block, img_w, img_h)
        if crop is None:
            continue

        # 2. 블록 크기에 맞는 프롬프트 선택
        prompt = _select_prompt(block)

        # 3. OCR 실행
        try:
            raw_text = _run_single_ocr(model, processor, device, crop, prompt, max_tokens)
            crop.close()
        except Exception as exc:
            logger.warning("블록 OCR 실패 (x=%d, y=%d): %s", block.x, block.y, exc)
            crop.close()
            continue

        # 4. 텍스트 정제 및 검증
        cleaned = clean_text(raw_text).strip()
        if not cleaned or len(cleaned) < 1:
            continue

        # 5. 정규화 좌표 계산
        bbox_norm = (
            block.x / img_w,
            block.y / img_h,
            block.x2 / img_w,
            block.y2 / img_h,
        )

        results.append(BlockOcrResult(
            block=block,
            text=cleaned,
            bbox_norm=bbox_norm,
        ))

    return results


def _crop_block(
    image: Image.Image,
    block: SentenceBlock,
    img_w: int,
    img_h: int,
) -> Image.Image | None:
    """블록 영역을 패딩 포함하여 크롭한다.

    글자가 잘리지 않도록 글자 높이 비례 패딩을 추가한다.
    """
    pad = int(block.char_height * _PADDING_RATIO)

    x1 = max(0, block.x - pad)
    y1 = max(0, block.y - pad)
    x2 = min(img_w, block.x2 + pad)
    y2 = min(img_h, block.y2 + pad)

    crop_w = x2 - x1
    crop_h = y2 - y1
    if crop_w < _MIN_CROP_SIZE or crop_h < _MIN_CROP_SIZE:
        return None

    return image.crop((x1, y1, x2, y2))


def _select_prompt(block: SentenceBlock) -> str:
    """블록 크기와 특성에 맞는 OCR 프롬프트를 선택한다."""
    from backend.ocr.prompt import OcrPrompt
    from backend.pdf.atoms.detect_text_blocks import BlockSize

    # SMALL 블록은 표 셀일 가능성이 높다
    if block.size == BlockSize.SMALL:
        return OcrPrompt.get_table_grounding()

    return OcrPrompt.get_grounding()


def _run_single_ocr(
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
