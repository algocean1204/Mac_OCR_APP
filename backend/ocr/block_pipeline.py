# 블록 기반 OCR 파이프라인 모듈
# 고급 텍스트 검출(CRAFT) → 행 단위 병합 → 기울기 보정 → 배치 OCR
# → 경량 LLM 교정 → 사전 기반 후처리(폴백) → 결과 병합
#
# 파이프라인 흐름:
# 1. CRAFT 딥러닝 모델로 단어/구 수준 텍스트 영역 검출
# 2. 같은 행의 블록을 문장 단위로 병합 (LLM 교정에 문맥 제공)
# 3. 기울어진 텍스트를 OpenCV affine transform으로 보정
# 4. GLM-OCR로 배치 단위 텍스트 인식
# 5. 경량 LLM(Qwen3-8B)으로 문맥 기반 교정 (오타/고유명사 분류)
# 6. 사전 기반 혼동 문자 보정 (LLM 교정 보조)
# 7. 읽기 순서로 결과 병합
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import torch
from PIL import Image

from backend.ocr.atoms.batch_ocr import RegionOcrResult, run_batch_ocr
from backend.ocr.atoms.block_ocr import BlockOcrResult, run_block_ocr
from backend.ocr.atoms.detect_text_regions import TextRegion, detect_text_regions
from backend.ocr.atoms.merge_sentence_blocks import SentenceBlock, merge_into_sentence_blocks
from backend.pdf.atoms.detect_text_blocks import BlockSize, TextBlock, detect_text_blocks

logger = logging.getLogger(__name__)


@dataclass
class PageBlockResult:
    """페이지 전체의 블록 기반 OCR 결과."""
    page_num: int
    block_results: list[BlockOcrResult]
    full_text: str  # 모든 블록 텍스트를 합친 전체 텍스트
    n_blocks_detected: int  # 감지된 초기 블록 수
    n_sentence_blocks: int  # 문장 단위 병합 후 블록 수
    n_ocr_results: int  # OCR 성공 블록 수


def run_page_block_pipeline(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    page_num: int = 0,
    max_tokens: int = 4096,
    use_craft: bool = True,
    use_llm_correction: bool = True,
) -> PageBlockResult:
    """단일 페이지에 대해 블록 기반 OCR 파이프라인을 실행한다.

    고급 파이프라인 (use_craft=True):
    1. CRAFT 텍스트 영역 검출 (단어/구 수준)
    2. 행 단위 문장 병합
    3. 기울기 보정 + 배치 OCR (GLM-OCR)
    4. 경량 LLM 교정 (Qwen3, 문맥 기반)
    5. 사전 기반 혼동 문자 보정 (보조)
    6. 결과 병합

    기본 파이프라인 (use_craft=False):
    1. Tesseract 기반 글자 크기별 블록 감지
    2. 문장 단위 병합
    3. 블록별 OCR
    4. 후처리
    5. 결과 병합
    """
    if use_craft:
        return _run_craft_pipeline(
            model, processor, device, image, page_num, max_tokens,
            use_llm_correction,
        )
    return _run_tesseract_pipeline(model, processor, device, image, page_num, max_tokens)


def _run_craft_pipeline(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    page_num: int,
    max_tokens: int,
    use_llm_correction: bool = True,
) -> PageBlockResult:
    """CRAFT 기반 고급 파이프라인을 실행한다."""
    # 1단계: CRAFT 텍스트 영역 검출
    regions: list[TextRegion] = detect_text_regions(image)
    n_regions = len(regions)
    logger.info("페이지 %d: CRAFT %d개 영역 검출", page_num + 1, n_regions)

    if not regions:
        logger.info("페이지 %d: CRAFT 실패 — Tesseract 폴백", page_num + 1)
        return _run_tesseract_pipeline(
            model, processor, device, image, page_num, max_tokens,
        )

    # 1.5단계: 과대 검출 영역 분할 — 세로로 긴 영역을 줄 단위로 분할
    regions = _split_oversized_regions(regions, image)

    # 1.7단계: CRAFT가 놓친 텍스트를 Tesseract로 보충 감지
    regions = _supplement_with_tesseract(regions, image)

    # 2단계: 행 단위 문장 병합 — LLM 교정에 문맥을 제공한다
    sentence_regions = _merge_regions_into_rows(regions)
    n_sentences = len(sentence_regions)
    logger.info(
        "페이지 %d: %d개 영역 → %d개 문장 블록",
        page_num + 1, n_regions, n_sentences,
    )

    # 3단계: 배치 OCR (기울기 보정 포함)
    ocr_results: list[RegionOcrResult] = run_batch_ocr(
        model, processor, device, image, sentence_regions, max_tokens,
    )

    # 4단계: RegionOcrResult → BlockOcrResult 변환
    block_results: list[BlockOcrResult] = []
    for r in ocr_results:
        sb = SentenceBlock(
            x=r.region.x, y=r.region.y,
            x2=r.region.x2, y2=r.region.y2,
            size=BlockSize.MEDIUM,
            char_height=r.region.y2 - r.region.y,
            source_blocks=[],
        )
        block_results.append(BlockOcrResult(
            block=sb,
            text=r.text,
            bbox_norm=r.bbox_norm,
        ))

    # 4.5단계: 멀티라인 블록 분할 — OCR 결과에 여러 줄이면 줄별 블록으로 분할
    block_results = _split_multiline_blocks(block_results)

    # 5단계: 경량 LLM 교정 (문맥 기반)
    if use_llm_correction:
        block_results = _apply_llm_correction(block_results)

    # 6단계: 사전 기반 후처리 (LLM 교정 보조)
    block_results = _apply_dict_post_processing(block_results)

    # 7단계: 결과 병합
    block_results.sort(key=lambda r: (r.block.y, r.block.x))
    full_text = _merge_texts(block_results)

    return PageBlockResult(
        page_num=page_num,
        block_results=block_results,
        full_text=full_text,
        n_blocks_detected=n_regions,
        n_sentence_blocks=n_sentences,
        n_ocr_results=len(block_results),
    )


def _supplement_with_tesseract(
    craft_regions: list[TextRegion],
    image: Image.Image,
) -> list[TextRegion]:
    """CRAFT가 놓친 텍스트를 Tesseract로 보충 감지한다.

    CRAFT 블록에 포함되지 않는 Tesseract 감지 영역을 추가한다.
    이중 감지를 방지하기 위해, 기존 CRAFT 블록과 50% 이상 겹치는
    Tesseract 영역은 제외한다.
    """
    try:
        import pytesseract
    except ImportError:
        return craft_regions

    img_w, img_h = image.size

    try:
        data = pytesseract.image_to_data(
            image, lang="kor+eng", config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return craft_regions

    # Tesseract 단어 → 바운딩 박스
    tess_words: list[tuple[int, int, int, int]] = []
    for i in range(len(data["text"])):
        if int(data["conf"][i]) < 30:
            continue
        text = data["text"][i].strip()
        if not text:
            continue
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        if w < 5 or h < 5:
            continue
        tess_words.append((x, y, x + w, y + h))

    if not tess_words:
        return craft_regions

    # CRAFT 커버리지 체크 — Tesseract 영역이 기존 블록과 겹치는지 확인
    added: int = 0
    result = list(craft_regions)

    for tx1, ty1, tx2, ty2 in tess_words:
        t_area = (tx2 - tx1) * (ty2 - ty1)
        if t_area <= 0:
            continue

        # CRAFT 블록과의 겹침 비율 계산
        max_overlap_ratio: float = 0.0
        for cr in craft_regions:
            ox1 = max(tx1, cr.x)
            oy1 = max(ty1, cr.y)
            ox2 = min(tx2, cr.x2)
            oy2 = min(ty2, cr.y2)
            if ox1 < ox2 and oy1 < oy2:
                overlap = (ox2 - ox1) * (oy2 - oy1)
                ratio = overlap / t_area
                if ratio > max_overlap_ratio:
                    max_overlap_ratio = ratio

        # 50% 이상 겹치면 이미 CRAFT가 감지한 것이므로 건너뜀
        if max_overlap_ratio >= 0.5:
            continue

        # CRAFT가 놓친 영역 — 추가
        result.append(TextRegion(
            x=tx1, y=ty1, x2=tx2, y2=ty2,
            bbox_norm=(tx1 / img_w, ty1 / img_h, tx2 / img_w, ty2 / img_h),
            angle=0.0,
            confidence=0.7,
            polygon=None,
        ))
        added += 1

    if added > 0:
        logger.info("Tesseract 보충: %d개 영역 추가", added)
        result.sort(key=lambda r: (r.y, r.x))

    return result


def _merge_regions_into_rows(regions: list[TextRegion]) -> list[TextRegion]:
    """CRAFT 검출 영역을 행 단위로 병합한다.

    같은 행(Y 중심이 가까운)의 영역 중 수평으로 인접한 것만 병합한다.
    높이가 크게 다른 영역, 수평 간격이 큰 영역은 별도 블록으로 유지한다.
    """
    if not regions:
        return []

    # Y 위치로 정렬
    sorted_regions = sorted(regions, key=lambda r: (r.y, r.x))

    # 행 그룹화 — Y 중심이 가까우면 같은 행
    rows: list[list[TextRegion]] = [[sorted_regions[0]]]
    for region in sorted_regions[1:]:
        last_row = rows[-1]
        row_cy = sum((r.y + r.y2) / 2 for r in last_row) / len(last_row)
        r_cy = (region.y + region.y2) / 2
        avg_h = sum(r.y2 - r.y for r in last_row) / len(last_row)
        r_h = region.y2 - region.y

        # 같은 행 조건:
        # 1) Y 중심 차이가 평균 높이의 50% 이내
        # 2) 높이 비율이 3배 이내 (너무 다른 크기의 텍스트는 같은 행이 아님)
        y_close = abs(r_cy - row_cy) <= avg_h * 0.5
        h_similar = (min(avg_h, r_h) / max(avg_h, r_h, 1)) > 0.33

        if y_close and h_similar:
            last_row.append(region)
        else:
            rows.append([region])

    # 각 행 내에서 수평 간격 기반으로 그룹을 분할한 뒤 병합
    merged: list[TextRegion] = []
    for row in rows:
        if len(row) == 1:
            merged.append(row[0])
            continue

        # 행 내 X 순 정렬
        row.sort(key=lambda r: r.x)

        # 수평 간격이 평균 글자 높이의 1.5배 이상이면 별도 그룹으로 분리
        avg_h = sum(r.y2 - r.y for r in row) / len(row)
        gap_threshold = avg_h * 1.5

        groups: list[list[TextRegion]] = [[row[0]]]
        for r in row[1:]:
            prev = groups[-1][-1]
            gap = r.x - prev.x2
            if gap > gap_threshold:
                groups.append([r])
            else:
                groups[-1].append(r)

        # 각 그룹을 하나의 TextRegion으로 병합
        for group in groups:
            merged.append(_merge_region_group(group))

    return merged


def _merge_region_group(group: list[TextRegion]) -> TextRegion:
    """인접한 TextRegion 그룹을 하나로 병합한다."""
    if len(group) == 1:
        return group[0]

    x = min(r.x for r in group)
    y = min(r.y for r in group)
    x2 = max(r.x2 for r in group)
    y2 = max(r.y2 for r in group)

    nx1 = min(r.bbox_norm[0] for r in group)
    ny1 = min(r.bbox_norm[1] for r in group)
    nx2 = max(r.bbox_norm[2] for r in group)
    ny2 = max(r.bbox_norm[3] for r in group)

    avg_angle = sum(r.angle for r in group) / len(group)
    avg_conf = sum(r.confidence for r in group) / len(group)

    return TextRegion(
        x=x, y=y, x2=x2, y2=y2,
        bbox_norm=(nx1, ny1, nx2, ny2),
        angle=avg_angle,
        confidence=avg_conf,
        polygon=None,
    )


def _split_oversized_regions(
    regions: list[TextRegion],
    image: Image.Image,
) -> list[TextRegion]:
    """과대 검출된 CRAFT 영역을 수평 프로젝션 프로파일로 분할한다.

    세로로 긴 영역(높이/너비 > 2, 높이 > 이미지 5%)은
    내부의 빈 행(텍스트 없는 수평 구간)을 찾아 줄 단위로 분할한다.
    """
    import cv2
    import numpy as np

    img_w, img_h = image.size
    # 과대 판정 기준: 높이가 이미지의 5% 이상이고 세로가 가로보다 2배 이상
    min_split_h = img_h * 0.05

    result: list[TextRegion] = []
    img_array: np.ndarray | None = None

    for region in regions:
        rh = region.y2 - region.y
        rw = region.x2 - region.x

        if rh < min_split_h or rw <= 0 or rh / max(rw, 1) < 2.0:
            result.append(region)
            continue

        # 이미지 로드 (최초 1회)
        if img_array is None:
            img_array = np.array(image.convert("L"))

        # 영역 내 수평 프로젝션 프로파일 — 각 행의 어두운 픽셀 비율
        crop = img_array[region.y:region.y2, region.x:region.x2]
        # 이진화 (Otsu) — 텍스트 픽셀을 검출
        _, binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # 행별 텍스트 픽셀 비율
        row_density = binary.mean(axis=1) / 255.0

        # 빈 행 찾기 — 밀도가 임계값 미만인 연속 행 구간
        gap_threshold = 0.05
        min_gap_rows = max(3, rh // 30)  # 최소 3픽셀 이상의 빈 구간

        sub_regions = _find_horizontal_splits(
            region, row_density, gap_threshold, min_gap_rows, img_w, img_h,
        )

        if len(sub_regions) > 1:
            logger.info(
                "과대 영역 분할: (%d,%d)-(%d,%d) → %d개 서브 영역",
                region.x, region.y, region.x2, region.y2, len(sub_regions),
            )
            result.extend(sub_regions)
        else:
            result.append(region)

    return result


def _find_horizontal_splits(
    region: TextRegion,
    row_density: "np.ndarray",
    gap_threshold: float,
    min_gap_rows: int,
    img_w: int,
    img_h: int,
) -> list[TextRegion]:
    """수평 프로젝션 프로파일에서 빈 구간을 찾아 영역을 분할한다."""
    import numpy as np

    is_gap = row_density < gap_threshold
    n_rows = len(row_density)

    # 텍스트 구간 시작/끝 찾기
    segments: list[tuple[int, int]] = []
    in_text = False
    seg_start = 0

    for i in range(n_rows):
        if not is_gap[i] and not in_text:
            # 텍스트 구간 시작
            seg_start = i
            in_text = True
        elif is_gap[i] and in_text:
            # 빈 구간이 최소 길이 이상이면 분할 지점으로 인정
            gap_start = i
            gap_end = i
            while gap_end < n_rows and is_gap[gap_end]:
                gap_end += 1
            if gap_end - gap_start >= min_gap_rows:
                segments.append((seg_start, i))
                in_text = False

    # 마지막 텍스트 구간
    if in_text:
        segments.append((seg_start, n_rows))

    if len(segments) <= 1:
        return [region]

    # 각 세그먼트를 별도 TextRegion으로 변환
    sub_regions: list[TextRegion] = []
    for seg_start, seg_end in segments:
        y = region.y + seg_start
        y2 = region.y + seg_end

        # 너무 작은 세그먼트는 무시
        if y2 - y < 5:
            continue

        ny1 = y / img_h
        ny2 = y2 / img_h
        nx1 = region.bbox_norm[0]
        nx2 = region.bbox_norm[2]

        sub_regions.append(TextRegion(
            x=region.x, y=y, x2=region.x2, y2=y2,
            bbox_norm=(nx1, ny1, nx2, ny2),
            angle=region.angle,
            confidence=region.confidence,
            polygon=None,
        ))

    return sub_regions if sub_regions else [region]


def _split_multiline_blocks(
    results: list[BlockOcrResult],
) -> list[BlockOcrResult]:
    """OCR 결과에 여러 줄이 포함된 블록을 줄별로 분할한다.

    CRAFT가 여러 줄의 텍스트를 하나의 영역으로 검출한 경우,
    OCR 결과의 줄 수에 따라 블록을 균등 분할한다.
    단, 블록 높이가 작으면(한 줄 크기) 분할하지 않는다.
    """
    split_results: list[BlockOcrResult] = []

    for r in results:
        lines = [l for l in r.text.split("\n") if l.strip()]
        block_h = r.block.y2 - r.block.y
        nx1, ny1, nx2, ny2 = r.bbox_norm
        norm_h = ny2 - ny1

        # 분할 조건: 2줄 이상이고 블록 높이가 줄당 최소 높이의 2배 이상
        if len(lines) < 2 or norm_h < 0.02:
            split_results.append(r)
            continue

        # 줄별 균등 분할
        n_lines = len(lines)
        per_line_pixel_h = block_h / n_lines
        per_line_norm_h = norm_h / n_lines

        for i, line_text in enumerate(lines):
            if not line_text.strip():
                continue

            line_y = r.block.y + int(i * per_line_pixel_h)
            line_y2 = r.block.y + int((i + 1) * per_line_pixel_h)
            line_ny1 = ny1 + i * per_line_norm_h
            line_ny2 = ny1 + (i + 1) * per_line_norm_h

            sub_block = SentenceBlock(
                x=r.block.x, y=line_y,
                x2=r.block.x2, y2=line_y2,
                size=r.block.size,
                char_height=line_y2 - line_y,
                source_blocks=[],
            )
            split_results.append(BlockOcrResult(
                block=sub_block,
                text=line_text.strip(),
                bbox_norm=(nx1, line_ny1, nx2, line_ny2),
            ))

    return split_results


def _apply_llm_correction(
    results: list[BlockOcrResult],
) -> list[BlockOcrResult]:
    """경량 LLM으로 OCR 결과를 문맥 기반 교정한다."""
    try:
        from backend.ocr.atoms.lightweight_correction import (
            correct_blocks_with_llm,
            load_correction_model,
            unload_correction_model,
        )
    except ImportError:
        logger.info("경량 LLM 교정 모듈 미설치 — 건너뜀")
        return results

    try:
        llm_model, tokenizer = load_correction_model()
    except (FileNotFoundError, ImportError) as exc:
        logger.info("교정 LLM 로드 실패: %s — 사전 기반 후처리만 사용", exc)
        return results

    # 블록별 텍스트를 추출하여 배치 교정
    texts = [r.text for r in results]
    corrected_texts = correct_blocks_with_llm(texts, llm_model, tokenizer)

    # 교정된 텍스트를 블록에 적용
    corrected: list[BlockOcrResult] = []
    for r, new_text in zip(results, corrected_texts):
        corrected.append(BlockOcrResult(
            block=r.block,
            text=new_text,
            bbox_norm=r.bbox_norm,
        ))

    # 교정 모델 해제 — GLM-OCR과 메모리 충돌 방지
    unload_correction_model()

    return corrected


def _run_tesseract_pipeline(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    page_num: int,
    max_tokens: int,
) -> PageBlockResult:
    """Tesseract 기반 파이프라인을 실행한다 (폴백용)."""
    # 1단계: 블록 감지
    raw_blocks: list[TextBlock] = detect_text_blocks(image)
    n_raw = len(raw_blocks)
    logger.info("페이지 %d: %d개 블록 감지", page_num + 1, n_raw)

    if not raw_blocks:
        return PageBlockResult(
            page_num=page_num,
            block_results=[],
            full_text="",
            n_blocks_detected=0,
            n_sentence_blocks=0,
            n_ocr_results=0,
        )

    # 2단계: 문장 단위 병합
    sentence_blocks: list[SentenceBlock] = merge_into_sentence_blocks(raw_blocks, image)
    n_sentence = len(sentence_blocks)

    # 3단계: 블록별 OCR
    ocr_results: list[BlockOcrResult] = run_block_ocr(
        model, processor, device, image, sentence_blocks, max_tokens,
    )

    # 4단계: 후처리
    ocr_results = _apply_dict_post_processing(ocr_results)

    # 5단계: 결과 병합
    ocr_results.sort(key=lambda r: (r.block.y, r.block.x))
    full_text = _merge_texts(ocr_results)

    return PageBlockResult(
        page_num=page_num,
        block_results=ocr_results,
        full_text=full_text,
        n_blocks_detected=n_raw,
        n_sentence_blocks=n_sentence,
        n_ocr_results=len(ocr_results),
    )


def _apply_dict_post_processing(
    results: list[BlockOcrResult],
) -> list[BlockOcrResult]:
    """사전 기반 혼동 문자 보정을 적용한다 (LLM 교정 보조)."""
    from backend.ocr.atoms.correct_confusable_chars import correct_confusable_chars
    from backend.ocr.atoms.correct_multichar_confusions import correct_multichar_confusions
    from backend.ocr.atoms.domain_dictionary import load_domain_dictionary

    try:
        domain_dict = load_domain_dictionary()
    except Exception:
        return results

    if not domain_dict:
        return results

    corrected: list[BlockOcrResult] = []
    for r in results:
        try:
            # 반복 치환 — 다중 문자 오인식을 단계적으로 교정한다
            text = r.text
            for _ in range(3):
                prev = text
                text = correct_confusable_chars(text, domain_dict)
                text = correct_multichar_confusions(text, domain_dict)
                if text == prev:
                    break
            corrected.append(BlockOcrResult(
                block=r.block,
                text=text,
                bbox_norm=r.bbox_norm,
            ))
        except Exception:
            corrected.append(r)

    return corrected


def _merge_texts(results: list[BlockOcrResult]) -> str:
    """블록 OCR 결과를 읽기 순서로 합쳐 전체 텍스트를 생성한다.

    같은 행의 블록은 탭으로 구분하고, 다른 행은 개행으로 구분한다.
    """
    if not results:
        return ""

    lines: list[str] = []
    current_row_texts: list[str] = []
    prev_y_center: float = -1

    for r in results:
        y_center = (r.block.y + r.block.y2) / 2

        # 이전 블록과 Y 중심이 가까우면 같은 행으로 판단
        if prev_y_center >= 0:
            row_height = r.block.y2 - r.block.y
            if abs(y_center - prev_y_center) <= row_height * 0.5:
                current_row_texts.append(r.text)
                prev_y_center = y_center
                continue

        # 새로운 행 시작 — 이전 행을 저장
        if current_row_texts:
            lines.append("\t".join(current_row_texts))

        current_row_texts = [r.text]
        prev_y_center = y_center

    # 마지막 행 저장
    if current_row_texts:
        lines.append("\t".join(current_row_texts))

    return "\n".join(lines)
