# 청크 워커 모듈
# 독립 프로세스에서 모델을 로드하고 할당된 페이지를 OCR 처리한다
# multiprocessing.Process의 target 함수로 사용된다
#
# 후처리(LLM 교정)는 워커에서 수행하지 않는다.
# OCR 완료 후 메인 프로세스에서 순차적으로 후처리 모델을 로드하여 처리한다.
# 이렇게 분리하면 OCR 모델과 후처리 모델이 동시에 메모리를 점유하지 않는다.
from __future__ import annotations

import gc
import json
import os
import signal
from multiprocessing import Queue
from pathlib import Path
from typing import Any

import torch
from PIL import Image

from backend.ocr.atoms.correct_confusable_chars import correct_confusable_chars
from backend.ocr.atoms.correct_multichar_confusions import correct_multichar_confusions
from backend.ocr.atoms.detect_repetition import is_output_anomalous, remove_repetitive_output
from backend.ocr.atoms.domain_dictionary import load_domain_dictionary
from backend.ocr.text_cleaner import clean_text, is_prompt_leakage

# ── 워커 프로세스 수준 도메인 사전 캐시 ──────────────────────────────────────
# 워커 프로세스 기동 시 한 번만 로드하여 반복 파일 읽기를 방지한다
_worker_domain_dict: frozenset[str] | None = None


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
            _worker_domain_dict = frozenset()
    return _worker_domain_dict


def _apply_text_correction(text: str) -> str:
    """텍스트에 혼동 문자 보정을 적용한다.

    Args:
        text: OCR 추출 원본 텍스트

    Returns:
        혼동 문자 보정이 적용된 텍스트
    """
    domain_dict = _get_worker_domain_dict()
    if not domain_dict:
        return text

    try:
        corrected = correct_confusable_chars(text, domain_dict)
        corrected = correct_multichar_confusions(corrected, domain_dict)
        return corrected
    except Exception:
        return text


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
) -> None:
    """독립 프로세스에서 할당된 페이지들을 OCR 처리하고 결과를 JSON으로 저장한다.

    각 워커는 자체 모델 인스턴스를 로드하여 독립적으로 OCR을 수행한다.
    후처리(LLM 교정)는 워커에서 수행하지 않으며, 메인 프로세스에서 순차 처리한다.
    OCR 결과 텍스트와 메타데이터를 JSON 파일로 저장한다.

    Args:
        worker_id: 워커 식별자 (0, 1, ...)
        model_id: HuggingFace 모델 ID
        model_dir: 로컬 모델 디렉토리 경로
        pdf_path: 원본 PDF 파일 경로
        page_numbers: 처리할 페이지 번호 목록 (0-based)
        chunk_size: 청크당 최대 페이지 수
        dpi: PDF 렌더링 해상도
        ocr_timeout: 페이지당 OCR 타임아웃 (초)
        temp_dir: OCR 결과 JSON 저장 임시 디렉토리
        progress_queue: 메인 프로세스와 통신할 큐
        max_tokens: 페이지당 최대 생성 토큰 수
        max_image_size: 이미지 최대 크기 (픽셀, 긴 변 기준)
    """
    _suppress_third_party_output()

    try:
        # 1단계: OCR 모델 로드
        _send(progress_queue, worker_id, "log", message="OCR 모델 로드 시작")
        model, processor, device = _load_model(model_dir)
        _send(progress_queue, worker_id, "worker_ready")

        # 2단계: PDF 열기
        from backend.pdf.extractor import PdfExtractor

        extractor = PdfExtractor(dpi=dpi)
        extractor.open(Path(pdf_path))

        # 3단계: 페이지를 순차 처리하고 OCR 결과를 수집한다
        page_results: list[dict[str, object]] = []

        for page_num in page_numbers:
            try:
                result = _process_single_page(
                    worker_id=worker_id,
                    model=model,
                    processor=processor,
                    device=device,
                    extractor=extractor,
                    page_num=page_num,
                    ocr_timeout=ocr_timeout,
                    progress_queue=progress_queue,
                    max_tokens=max_tokens,
                    max_image_size=max_image_size,
                )
                page_results.append(result)
            except Exception as exc:
                # 페이지 처리 실패 — 빈 텍스트로 기록하여 페이지 순서를 유지한다
                page_results.append({
                    "page_num": page_num,
                    "text": "",
                    "error": str(exc),
                })
                _send(progress_queue, worker_id, "page_error",
                      page_num=page_num, error=str(exc))

            # 완료 보고 (성공/실패 무관하게 항상 전송)
            _send(progress_queue, worker_id, "page_done", page_num=page_num)

            # 메모리 관리: chunk_size 페이지마다 GC 수행
            if len(page_results) % chunk_size == 0:
                _force_gc()

        # 4단계: OCR 결과를 JSON으로 저장한다
        result_path = Path(temp_dir) / f"ocr_results_worker_{worker_id}.json"
        _save_results(page_results, result_path)

        # 5단계: 정리
        extractor.close()
        _send(progress_queue, worker_id, "worker_done")

    except Exception as exc:
        _send(progress_queue, worker_id, "worker_error", error=str(exc))


def _process_single_page(
    worker_id: int,
    model: Any,
    processor: Any,
    device: torch.device,
    extractor: Any,
    page_num: int,
    ocr_timeout: int,
    progress_queue: Queue,
    max_tokens: int,
    max_image_size: int,
) -> dict[str, object]:
    """단일 페이지를 OCR 처리하고 결과를 딕셔너리로 반환한다.

    블록 파이프라인을 우선 시도하고, 실패 시 기존 전체 페이지 OCR로 폴백한다.

    Args:
        worker_id: 워커 식별자
        model: 로드된 transformers 모델
        processor: 로드된 프로세서
        device: torch 장치
        extractor: PDF 이미지 추출기
        page_num: 처리할 페이지 번호 (0-based)
        ocr_timeout: OCR 타임아웃 (초)
        progress_queue: 메인 프로세스 통신 큐
        max_tokens: 최대 생성 토큰 수
        max_image_size: 이미지 최대 크기 (픽셀)

    Returns:
        {"page_num": int, "text": str, "block_results": list[dict] | None} 딕셔너리
    """
    image: Image.Image | None = None

    try:
        image = extractor.extract_page_image(page_num)

        # 블록 파이프라인 시도
        block_results = _try_block_pipeline(
            model, processor, device, image, page_num, max_tokens,
        )

        if block_results is not None:
            # 블록 결과에서 전체 텍스트 추출
            full_text = "\n".join(br["text"] for br in block_results if br.get("text"))
            full_text = _apply_text_correction(full_text)
            return {
                "page_num": page_num,
                "text": full_text,
                "block_results": block_results,
            }

        # 폴백: 기존 전체 페이지 OCR
        plain_text = _run_ocr(
            model, processor, device, image,
            ocr_timeout, max_tokens, max_image_size,
        )
        plain_text = _apply_text_correction(plain_text)
        return {"page_num": page_num, "text": plain_text, "block_results": None}

    finally:
        if image is not None:
            try:
                image.close()
            except Exception:
                pass


def _try_block_pipeline(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    page_num: int,
    max_tokens: int,
) -> list[dict] | None:
    """블록 파이프라인으로 OCR을 시도한다.

    블록 감지 → 문장 병합 → 블록별 OCR → 후처리.
    실패하거나 블록이 없으면 None을 반환하여 폴백을 유도한다.
    """
    try:
        from backend.ocr.block_pipeline import run_page_block_pipeline

        result = run_page_block_pipeline(
            model, processor, device, image,
            page_num=page_num, max_tokens=max_tokens,
        )

        if result.n_ocr_results == 0:
            return None

        # 직렬화 가능한 딕셔너리 목록으로 변환
        block_dicts: list[dict] = []
        for br in result.block_results:
            block_dicts.append({
                "text": br.text,
                "bbox_norm": list(br.bbox_norm),
                "size": br.block.size.value,
                "char_height": br.block.char_height,
            })

        return block_dicts

    except Exception:
        return None


def _save_results(results: list[dict[str, object]], path: Path) -> None:
    """OCR 결과 목록을 JSON 파일로 저장한다.

    Args:
        results: 페이지별 OCR 결과 딕셔너리 목록
        path: 저장할 JSON 파일 경로
    """
    path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")


def _load_model(model_dir: str) -> tuple[Any, Any, torch.device]:
    """transformers 모델과 프로세서를 로드하여 반환한다.

    Args:
        model_dir: 로컬 모델 디렉토리 경로 또는 HuggingFace 모델 ID

    Returns:
        (model, processor, device) 튜플
    """
    from transformers import AutoModelForImageTextToText, Glm46VProcessor

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    processor = Glm46VProcessor.from_pretrained(model_dir)
    model = AutoModelForImageTextToText.from_pretrained(
        pretrained_model_name_or_path=model_dir,
        dtype=torch.bfloat16,
    ).to(device)

    return model, processor, device


def _run_ocr(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    timeout_seconds: int,
    max_tokens: int,
    max_image_size: int,
) -> str:
    """GLM-OCR로 OCR을 실행하고 정제된 텍스트를 반환한다.

    Args:
        model: 로드된 transformers 모델 인스턴스
        processor: 로드된 AutoProcessor 인스턴스
        device: torch 장치 (mps 또는 cpu)
        image: 원본 PIL Image 객체
        timeout_seconds: 페이지당 OCR 타임아웃 (초)
        max_tokens: 페이지당 최대 생성 토큰 수
        max_image_size: 이미지 최대 크기 (픽셀, 긴 변 기준)
    """
    from backend.ocr.atoms.quick_table_check import quick_table_check
    from backend.ocr.prompt import OcrPrompt

    resized = _resize_if_needed(image, max_image_size)

    # 표 존재 여부에 따라 프롬프트를 선택한다
    has_table = quick_table_check(resized)
    ocr_prompt = OcrPrompt.get_table_grounding() if has_table else OcrPrompt.get_grounding()

    # SIGALRM 기반 타임아웃 (Unix 전용)
    def _timeout_handler(signum: int, frame: object) -> None:
        raise TimeoutError()

    original_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_seconds)

    try:
        # 1단계: 추론 실행
        raw = _generate_text(model, processor, device, resized, ocr_prompt, max_tokens)

        # 2단계: 환각 반복 출력 감지
        if is_output_anomalous(raw):
            raw = remove_repetitive_output(raw)

        # 3단계: 프롬프트 누출 검사
        stripped = raw.strip()
        if not stripped or len(stripped) < 5:
            return ""
        if is_prompt_leakage(stripped):
            return ""

        # 4단계: 텍스트 정제
        return clean_text(raw)

    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)
        if resized is not image:
            resized.close()


def _generate_text(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    prompt: str,
    max_tokens: int,
) -> str:
    """GLM-OCR 모델로 추론을 실행하고 원시 텍스트를 반환한다.

    Args:
        model: 로드된 transformers 모델 인스턴스
        processor: 로드된 AutoProcessor 인스턴스
        device: torch 장치
        image: PIL Image 객체
        prompt: OCR 프롬프트 문자열
        max_tokens: 최대 생성 토큰 수

    Returns:
        모델 출력 원시 텍스트
    """
    # chat template 기반 메시지 구성
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

    # 입력 토큰을 제외하고 생성된 토큰만 디코딩한다
    input_len = inputs["input_ids"].shape[1]
    return processor.decode(outputs[0][input_len:], skip_special_tokens=True)


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
    """가비지 컬렉션과 torch MPS 캐시 정리를 강제로 실행한다."""
    gc.collect()
    try:
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except (AttributeError, RuntimeError):
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
