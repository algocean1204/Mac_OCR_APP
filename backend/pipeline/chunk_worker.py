# 청크 워커 모듈
# 독립 프로세스에서 모델을 로드하고 할당된 페이지를 OCR 처리한다
# multiprocessing.Process의 target 함수로 사용된다
from __future__ import annotations

import gc
import os
import signal
import tempfile
from multiprocessing import Queue
from pathlib import Path
from typing import Any

from PIL import Image

from backend.ocr.atoms.correct_confusable_chars import correct_confusable_chars
from backend.ocr.atoms.correct_multichar_confusions import correct_multichar_confusions
from backend.ocr.atoms.detect_repetition import is_output_anomalous, remove_repetitive_output
from backend.ocr.atoms.domain_dictionary import load_domain_dictionary
from backend.ocr.atoms.split_page import remap_blocks_to_original, split_page_image
from backend.ocr.grounding_parser import OcrBlock, parse_grounding_output
from backend.ocr.post_processor import PostProcessor
from backend.ocr.text_cleaner import clean_text, is_prompt_leakage

# ── 워커 프로세스 수준 도메인 사전 캐시 ──────────────────────────────────────
# 워커 프로세스 기동 시 한 번만 로드하여 반복 파일 읽기를 방지한다
_worker_domain_dict: frozenset[str] | None = None

# ── 워커 프로세스 수준 후처리 엔진 캐시 ────────────────────────────────────────
# 워커 기동 시 한 번만 로드하여 반복 초기화를 방지한다
_worker_post_processor: PostProcessor | None = None


def _get_worker_domain_dict() -> frozenset[str]:
    """워커 프로세스의 도메인 사전을 지연 초기화하여 반환한다.

    최초 호출 시 파일을 읽고, 이후에는 캐시를 반환한다.
    로드 실패 시 빈 frozenset으로 안전하게 처리한다.
    """
    global _worker_domain_dict
    if _worker_domain_dict is None:
        try:
            _worker_domain_dict = load_domain_dictionary()
        except Exception:
            # 사전 로드 실패 — 보정 비활성화로 안전 처리
            _worker_domain_dict = frozenset()
    return _worker_domain_dict


def _apply_correction_to_blocks(blocks: list[OcrBlock]) -> list[OcrBlock]:
    """grounding 블록 목록의 각 텍스트에 혼동 문자 보정을 적용한다.

    보정은 보수적으로 수행된다. 사전 매칭이 확실한 경우에만 수정하고,
    bbox_norm, block_type, truncated 등 다른 속성은 변경하지 않는다.
    보정 중 예외가 발생하면 원본 블록을 그대로 유지한다.

    Args:
        blocks: 파싱된 OcrBlock 리스트

    Returns:
        혼동 문자 보정이 적용된 새 OcrBlock 리스트
    """
    domain_dict = _get_worker_domain_dict()
    # 사전이 비어 있으면 보정 불가 — 원본 반환
    if not domain_dict:
        return blocks

    corrected: list[OcrBlock] = []
    for block in blocks:
        try:
            # 1단계: 단일 문자 혼동 보정 (CONFUSION_MAP 기반)
            corrected_text = correct_confusable_chars(block.text, domain_dict)
            # 2단계: 자모 수준 다중 문자 혼동 보정 (초성/중성/종성 치환)
            corrected_text = correct_multichar_confusions(corrected_text, domain_dict)
            corrected.append(OcrBlock(
                text=corrected_text,
                block_type=block.block_type,
                bbox_norm=block.bbox_norm,
                truncated=block.truncated,
            ))
        except Exception:
            # 개별 블록 보정 실패 — 원본 블록 유지
            corrected.append(block)

    return corrected


def _load_post_processor(model_id: str, model_dir: str) -> None:
    """후처리 LLM 모델을 로드하여 워커 수준에서 캐시한다.

    Args:
        model_id: HuggingFace 모델 ID
        model_dir: 로컬 모델 디렉토리 경로
    """
    global _worker_post_processor
    if _worker_post_processor is not None and _worker_post_processor.is_loaded():
        return

    _worker_post_processor = PostProcessor()
    model_path = Path(model_dir) if model_dir else None
    _worker_post_processor.load_model(model_id, model_path)


def run_worker(
    worker_id: int,
    model_id: str,
    model_dir: str,
    pdf_path: str,
    page_numbers: list[int],
    chunk_size: int,
    dpi: int,
    ocr_timeout: int,
    temp_dir: str,
    progress_queue: Queue,
    max_tokens: int,
    max_image_size: int,
    post_model_id: str = "",
    post_model_dir: str = "",
    enable_post_process: bool = False,
    post_process_mode: str = "korean",
) -> None:
    """독립 프로세스에서 할당된 페이지들을 OCR 처리하고 청크 PDF로 저장한다.

    각 워커는 자체 모델 인스턴스를 로드하여 독립적으로 OCR을 수행한다.
    chunk_size 페이지마다 하나의 PDF 파일로 저장하여 메모리 누적을 방지한다.

    Args:
        worker_id: 워커 식별자 (0, 1, ...)
        model_id: HuggingFace 모델 ID
        model_dir: 로컬 모델 디렉토리 경로
        pdf_path: 원본 PDF 파일 경로
        page_numbers: 처리할 페이지 번호 목록 (0-based)
        chunk_size: 청크당 최대 페이지 수
        dpi: PDF 렌더링 해상도
        ocr_timeout: 페이지당 OCR 타임아웃 (초)
        temp_dir: 청크 PDF 저장 임시 디렉토리
        progress_queue: 메인 프로세스와 통신할 큐
        max_tokens: 페이지당 최대 생성 토큰 수
        max_image_size: 이미지 최대 크기 (픽셀, 긴 변 기준)
        post_model_id: 후처리 LLM 모델 ID
        post_model_dir: 후처리 LLM 로컬 모델 디렉토리 경로
        enable_post_process: 후처리 활성화 여부
        post_process_mode: 후처리 모드 ("korean" 또는 "reasoning")
    """
    _suppress_third_party_output()

    try:
        # 1단계: 모델 로드
        _send(progress_queue, worker_id, "log", message="모델 로드 시작")
        model, processor = _load_model(model_dir)
        _send(progress_queue, worker_id, "worker_ready")

        # 1-b단계: 후처리 모델 로드 (활성화 시)
        if enable_post_process and post_model_id:
            _send(progress_queue, worker_id, "log", message="후처리 모델 로드 시작")
            _load_post_processor(post_model_id, post_model_dir)
            _send(progress_queue, worker_id, "log", message="후처리 모델 로드 완료")

        # 2단계: PDF 열기
        from backend.pdf.extractor import PdfExtractor

        extractor = PdfExtractor(dpi=dpi)
        extractor.open(Path(pdf_path))

        # 3단계: 페이지를 청크 단위로 처리
        for chunk_start in range(0, len(page_numbers), chunk_size):
            chunk_pages = page_numbers[chunk_start:chunk_start + chunk_size]
            # 파일명에 전역 페이지 번호를 포함하여 병합 시 정렬이 가능하다
            chunk_path = Path(temp_dir) / f"chunk_{chunk_pages[0]:06d}.pdf"

            _process_chunk(
                worker_id=worker_id,
                model=model,
                processor=processor,
                extractor=extractor,
                chunk_pages=chunk_pages,
                chunk_path=chunk_path,
                ocr_timeout=ocr_timeout,
                progress_queue=progress_queue,
                max_tokens=max_tokens,
                max_image_size=max_image_size,
                enable_post_process=enable_post_process,
                post_process_mode=post_process_mode,
            )

            _send(progress_queue, worker_id, "chunk_saved",
                  chunk_path=str(chunk_path))

        # 4단계: 정리
        extractor.close()
        _send(progress_queue, worker_id, "worker_done")

    except Exception as exc:
        _send(progress_queue, worker_id, "worker_error", error=str(exc))


def _process_chunk(
    worker_id: int,
    model: Any,
    processor: Any,
    extractor: Any,
    chunk_pages: list[int],
    chunk_path: Path,
    ocr_timeout: int,
    progress_queue: Queue,
    max_tokens: int,
    max_image_size: int,
    enable_post_process: bool = False,
    post_process_mode: str = "korean",
) -> None:
    """한 청크(최대 chunk_size 페이지)를 처리하고 PDF로 저장한다."""
    from backend.pdf.generator import PdfGenerator

    generator = PdfGenerator(chunk_path)

    for page_num in chunk_pages:
        image: Image.Image | None = None

        try:
            # 이미지 추출
            image = extractor.extract_page_image(page_num)
            page_width, page_height = extractor.get_page_size(page_num)

            # OCR 추론
            try:
                ocr_result = _run_ocr(
                    model, processor, image, ocr_timeout, max_tokens, max_image_size
                )
                if isinstance(ocr_result, list):
                    # grounding 모드 — 표 감지 후처리를 적용한 뒤 좌표 기반 배치를 사용한다
                    img_w, img_h = image.size
                    # OpenCV 표 영역 감지로 격자 데이터를 확보한다 (reconstruct에 활용)
                    pre_detected_regions = _detect_table_regions_from_image(image)
                    processed_blocks = _post_process_blocks(
                        ocr_result, image, img_w, img_h,
                        table_regions=pre_detected_regions,
                    )
                    # 후처리 LLM 교정 적용 (활성화 시)
                    if enable_post_process and _worker_post_processor is not None:
                        try:
                            processed_blocks = _worker_post_processor.refine_blocks(
                                processed_blocks, mode=post_process_mode
                            )
                        except Exception:
                            pass  # 후처리 실패 — 원본 블록 유지
                    generator.add_page_with_blocks(
                        image, processed_blocks, page_width, page_height, img_w, img_h
                    )
                else:
                    # plain text 폴백
                    plain_text = ocr_result
                    if enable_post_process and _worker_post_processor is not None:
                        try:
                            plain_text = _worker_post_processor.refine_text(
                                plain_text, mode=post_process_mode
                            )
                        except Exception:
                            pass  # 후처리 실패 — 원본 텍스트 유지
                    generator.add_page(image, plain_text, page_width, page_height)
            except Exception:
                # OCR 실패 시 이미지만 추가한다
                generator.add_image_only_page(image, page_width, page_height)
                _send(progress_queue, worker_id, "page_error",
                      page_num=page_num, error="OCR 실패 — 이미지만 추가")

        except Exception as exc:
            # 이미지 추출 실패 — 해당 페이지를 건너뛴다
            _send(progress_queue, worker_id, "page_error",
                  page_num=page_num, error=str(exc))

        finally:
            # 메모리 즉시 해제
            if image is not None:
                try:
                    image.close()
                except Exception:
                    pass

        # 완료 보고 (성공/실패 무관하게 항상 전송)
        _send(progress_queue, worker_id, "page_done", page_num=page_num)

    # 청크 완료 시점에 GC 수행 — 매 페이지 대신 청크 단위로 호출하여 오버헤드를 줄인다
    _force_gc()

    # 청크에 페이지가 하나도 없을 수 있다 (모든 페이지 추출 실패 시)
    if generator.page_count > 0:
        generator.save()


def _detect_table_regions_from_image(image: Image.Image) -> "list | None":
    """PIL 이미지에서 OpenCV 기반 표 영역을 감지하고 격자 데이터와 함께 반환한다.

    감지 실패 시 None을 반환하여 호출자가 폴백 감지를 수행하도록 한다.
    격자 데이터(h/v 선 위치)가 포함된 TableRegion 목록을 반환한다.

    Args:
        image: 원본 PIL Image 객체

    Returns:
        감지된 TableRegion 목록, 오류 발생 시 None
    """
    try:
        import numpy as np
        from backend.ocr.atoms.detect_table_region import detect_table_regions

        # PIL Image → OpenCV BGR numpy 배열 변환
        rgb_array = np.array(image.convert("RGB"))
        bgr_array = rgb_array[:, :, ::-1].copy()
        return detect_table_regions(bgr_array)
    except Exception:
        # 감지 오류는 파이프라인을 중단시키지 않는다
        return None


def _post_process_blocks(
    blocks: list[OcrBlock],
    image: "Image.Image",
    img_w: int,
    img_h: int,
    table_regions: "list | None" = None,
) -> list[OcrBlock]:
    """OCR 블록에 표 구조 감지 및 재구성 후처리를 적용한다.

    table_regions가 미리 감지된 경우 해당 정보를 재사용한다.
    없으면 PIL 이미지를 numpy 배열로 변환하여 직접 감지한다.
    감지된 표 영역이 있을 때만 reconstruct_table_text를 호출한다.
    오류 발생 시 원본 블록을 그대로 반환하여 파이프라인을 보호한다.

    Args:
        blocks: OCR으로 생성된 원본 블록 목록
        image: 페이지 PIL Image 객체
        img_w: 이미지 너비 (픽셀)
        img_h: 이미지 높이 (픽셀)
        table_regions: 미리 감지된 표 영역 목록 (격자 데이터 포함 가능), None이면 직접 감지

    Returns:
        표 구조가 재구성된 블록 목록 (표 없는 페이지는 원본 반환)
    """
    try:
        import numpy as np
        from backend.ocr.atoms.detect_table_region import detect_table_regions
        from backend.ocr.atoms.reconstruct_table import reconstruct_table_text

        # 미리 감지된 영역이 없으면 직접 OpenCV 감지를 수행한다
        if table_regions is None:
            rgb_array = np.array(image.convert("RGB"))
            bgr_array = rgb_array[:, :, ::-1].copy()
            table_regions = detect_table_regions(bgr_array)

        if not table_regions:
            # 표가 없는 페이지는 원본 블록을 그대로 반환한다
            return blocks

        # 격자 데이터가 포함된 TableRegion을 그대로 전달하여 적응형 재구성에 활용한다
        return reconstruct_table_text(blocks, table_regions, img_w, img_h)

    except Exception:
        # 후처리 오류는 파이프라인을 중단시키지 않는다
        return blocks


def _load_model(model_dir: str) -> tuple[Any, Any]:
    """mlx-vlm 모델과 프로세서를 로드하여 반환한다."""
    from mlx_vlm import load as mlx_load

    return mlx_load(model_dir, trust_remote_code=True)


def _run_ocr(
    model: Any,
    processor: Any,
    image: Image.Image,
    timeout_seconds: int,
    max_tokens: int,
    max_image_size: int,
) -> list[OcrBlock] | str:
    """grounding 모드로 OCR을 실행하고, 실패 시 plain text 폴백을 반환한다.

    mlx_vlm.generate는 이미지 파일 경로(str)를 받으므로
    PIL Image를 임시 파일에 저장한 뒤 경로를 전달한다.
    SIGALRM으로 타임아웃을 구현한다 (워커 프로세스의 메인 스레드에서 동작).
    OCR 실행 전 quick_table_check로 표 존재 여부를 사전 판정하고,
    표가 감지된 경우 TABLE_GROUNDING 프롬프트를 사용한다.

    Args:
        model: 로드된 mlx-vlm 모델 인스턴스
        processor: 로드된 mlx-vlm 프로세서 인스턴스
        image: 원본 PIL Image 객체
        timeout_seconds: 페이지당 OCR 타임아웃 (초)
        max_tokens: 페이지당 최대 생성 토큰 수
        max_image_size: 이미지 최대 크기 (픽셀, 긴 변 기준)
    """
    from mlx_vlm import generate as mlx_generate
    from backend.ocr.atoms.quick_table_check import quick_table_check
    from backend.ocr.prompt import OcrPrompt

    resized = _resize_if_needed(image, max_image_size)

    # OCR 전 경량 표 사전 감지로 적절한 프롬프트를 선택한다 (< 20ms 목표)
    has_table = quick_table_check(resized)
    ocr_prompt = OcrPrompt.get_table_grounding() if has_table else OcrPrompt.get_grounding()

    # PIL Image를 임시 PNG 파일로 저장한다
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        resized.save(tmp, format="PNG")
        tmp_path = tmp.name

    # SIGALRM 기반 타임아웃 (Unix 전용, 워커 메인 스레드에서 동작)
    def _timeout_handler(signum: int, frame: object) -> None:
        raise TimeoutError()

    original_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_seconds)

    try:
        # 1단계: 표 감지 결과에 따른 프롬프트로 추론한다
        raw = _generate_and_extract(mlx_generate, model, processor, ocr_prompt, tmp_path, max_tokens)

        # 2단계: 환각 반복 출력 감지 — 원시 출력이 비정상적으로 길면 반복을 제거한다
        if is_output_anomalous(raw):
            raw = remove_repetitive_output(raw)

        # 3단계: grounding 출력을 파싱하여 블록 목록을 얻는다 (잘림 감지 포함)
        blocks = parse_grounding_output(raw, max_tokens=max_tokens)

        # 3-a: TABLE_GROUNDING 안전장치 — 환각이 의심되면 기본 GROUNDING으로 재시도한다
        # 블록 내 합계 텍스트가 비정상적으로 길면 TABLE_GROUNDING이 환각을 유발한 것으로 판정
        if blocks and has_table:
            total_block_text = sum(len(b.text) for b in blocks)
            if is_output_anomalous("\n".join(b.text for b in blocks)):
                # 기본 GROUNDING으로 재시도한다
                signal.alarm(timeout_seconds)
                raw_retry = _generate_and_extract(
                    mlx_generate, model, processor,
                    OcrPrompt.get_grounding(), tmp_path, max_tokens,
                )
                if is_output_anomalous(raw_retry):
                    raw_retry = remove_repetitive_output(raw_retry)
                retry_blocks = parse_grounding_output(raw_retry, max_tokens=max_tokens)
                if retry_blocks:
                    retry_text = sum(len(b.text) for b in retry_blocks)
                    # 재시도 결과가 더 합리적이면 채택한다
                    if retry_text < total_block_text:
                        blocks = retry_blocks

        if blocks:
            # 마지막 블록이 잘린 경우 — 페이지를 분할하여 재-OCR을 시도한다
            if blocks[-1].truncated:
                merged = _ocr_split_halves(
                    model, processor, resized,
                    max_tokens, timeout_seconds,
                )
                if merged:
                    # 분할 재-OCR 결과에도 혼동 문자 보정을 적용한다
                    return _apply_correction_to_blocks(merged)
            # grounding 블록 텍스트에 혼동 문자 보정을 적용한다
            return _apply_correction_to_blocks(blocks)

        # 4단계: grounding 블록이 0개인 경우 — 사전 감지
        stripped_raw = raw.strip()
        # 거의 빈 응답 — 이미지 전용/빈 페이지로 판정
        if not stripped_raw or len(stripped_raw) < 5:
            return ""
        # 1차 추론 결과가 프롬프트 누출이면 2차 추론도 동일하게 실패할 가능성이 높다
        if is_prompt_leakage(stripped_raw):
            return ""

        # 5단계: 의미있는 텍스트가 있으면 타이머를 리셋하고 plain text로 재시도한다
        signal.alarm(timeout_seconds)
        raw_plain = _generate_and_extract(
            mlx_generate, model, processor,
            OcrPrompt.get_plain_text(), tmp_path, max_tokens,
        )
        # plain text 결과도 반복 검사를 적용한다
        if is_output_anomalous(raw_plain):
            raw_plain = remove_repetitive_output(raw_plain)
        # clean_text 내부에서 is_prompt_leakage 안전망이 작동한다
        # clean_text는 자체적으로 혼동 문자 보정을 포함하므로 추가 호출 불필요
        return clean_text(raw_plain)

    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)
        # 임시 파일 정리
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        if resized is not image:
            resized.close()


def _generate_and_extract(
    mlx_generate: Any,
    model: Any,
    processor: Any,
    prompt: str,
    image_path: str,
    max_tokens: int,
) -> str:
    """mlx_generate를 실행하고 원시 텍스트를 추출한다.

    GenerationResult 또는 문자열 타입을 통합 처리한다.

    Args:
        mlx_generate: mlx_vlm.generate 함수 참조
        model: 로드된 mlx-vlm 모델 인스턴스
        processor: 로드된 mlx-vlm 프로세서 인스턴스
        prompt: OCR 프롬프트 문자열
        image_path: 임시 PNG 파일 경로
        max_tokens: 최대 생성 토큰 수

    Returns:
        모델 출력 원시 텍스트
    """
    gen_result = mlx_generate(
        model, processor, prompt,
        image=image_path, max_tokens=max_tokens, verbose=False,
    )
    return gen_result.text if hasattr(gen_result, "text") else str(gen_result)


def _ocr_split_halves(
    model: Any,
    processor: Any,
    image: Image.Image,
    max_tokens: int,
    timeout_seconds: int,
) -> list[OcrBlock] | None:
    """잘림이 감지된 페이지를 상/하로 분할하여 각각 OCR하고 결과를 병합한다.

    재시도는 단 1회만 수행한다. 분할 이미지도 잘린 경우 그 결과를 그대로 사용한다.

    Args:
        model: 로드된 mlx-vlm 모델 인스턴스
        processor: 로드된 mlx-vlm 프로세서 인스턴스
        image: 원본(리사이즈 후) PIL Image 객체
        max_tokens: 페이지당 최대 생성 토큰 수
        timeout_seconds: 분할 이미지당 OCR 타임아웃 (초)

    Returns:
        병합된 OcrBlock 리스트, 실패 시 None
    """
    from mlx_vlm import generate as mlx_generate
    from backend.ocr.prompt import OcrPrompt

    halves = split_page_image(image)
    total_height = image.size[1]

    # 원본 이미지에서 분할 지점의 픽셀 y 좌표를 정규화 좌표로 변환한다
    # 상단 이미지 높이 = crop 하단 경계 (overlap 포함)
    top_height = halves[0].size[1]
    split_y_norm = int((top_height / total_height) * 999)

    all_blocks: list[OcrBlock] = []

    for half_index, half_image in enumerate(halves):
        half_tmp_path: str | None = None
        try:
            # 분할 이미지를 임시 파일로 저장한다
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as half_tmp:
                half_image.save(half_tmp, format="PNG")
                half_tmp_path = half_tmp.name

            gen_result = mlx_generate(
                model,
                processor,
                OcrPrompt.get_grounding(),
                image=half_tmp_path,
                max_tokens=max_tokens,
                verbose=False,
            )
            raw_half: str = (
                gen_result.text if hasattr(gen_result, "text") else str(gen_result)
            )

            # 분할 이미지 블록 파싱 (잘림 감지 포함 — 재귀 분할은 하지 않음)
            half_blocks = parse_grounding_output(raw_half, max_tokens=max_tokens)
            if not half_blocks:
                continue

            # 분할 이미지 좌표를 원본 이미지 좌표로 재매핑한다
            remapped = remap_blocks_to_original(
                half_blocks,
                half_index=half_index,
                split_y_norm=split_y_norm,
                total_height=total_height,
                half_height=half_image.size[1],
            )
            all_blocks.extend(remapped)

        except Exception:
            # 분할 OCR 실패는 조용히 건너뛴다 — 반대편 절반이라도 활용한다
            pass
        finally:
            if half_tmp_path is not None:
                try:
                    Path(half_tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                half_image.close()
            except Exception:
                pass

    return all_blocks if all_blocks else None


def _resize_if_needed(image: Image.Image, max_image_size: int) -> Image.Image:
    """이미지가 최대 크기를 초과하면 비율을 유지하며 축소한다.

    Args:
        image: 원본 PIL Image 객체
        max_image_size: 허용할 최대 픽셀 크기 (가로/세로 중 긴 변 기준)
    """
    width, height = image.size
    if width <= max_image_size and height <= max_image_size:
        return image
    ratio = max_image_size / max(width, height)
    new_width = int(width * ratio)
    new_height = int(height * ratio)
    return image.resize((new_width, new_height), Image.LANCZOS)


def _force_gc() -> None:
    """가비지 컬렉션과 MLX 캐시 정리를 강제로 실행한다."""
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except (ImportError, AttributeError):
        pass


def _suppress_third_party_output() -> None:
    """서드파티 라이브러리의 stdout/stderr 출력을 억제한다."""
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def _send(
    queue: Queue,
    worker_id: int,
    msg_type: str,
    **kwargs: object,
) -> None:
    """Queue를 통해 메인 프로세스에 메시지를 전송한다."""
    msg: dict[str, object] = {
        "type": msg_type,
        "worker_id": worker_id,
        **kwargs,
    }
    queue.put(msg)
