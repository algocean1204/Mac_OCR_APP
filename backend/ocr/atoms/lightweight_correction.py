# 경량 LLM 기반 OCR 교정 모듈
# GLM-OCR 결과를 문맥 기반으로 교정한다
# Qwen3-8B-4bit (mlx-lm)를 사용하여 오타/고유명사를 분류·교정한다
#
# 하드코딩된 혼동 문자 사전 대신 LLM이 문맥을 보고 판단하므로:
#   - 새로운 PDF에도 범용 적용 가능
#   - 고유명사 vs 오타 구분 가능
#   - 다의적 혼동(같은 글자가 여러 올바른 글자로 매핑)도 문맥으로 해결
from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# mlx-lm 모델 싱글톤 — 프로세스 당 한 번만 로드한다
_correction_model: Any | None = None
_correction_tokenizer: Any | None = None

# 교정 프롬프트 — 짧고 구체적으로 지시한다
_CORRECTION_PROMPT: str = (
    "OCR로 인식된 한국어 텍스트입니다. 오타만 교정하세요.\n"
    "규칙: 원본 구조 유지, 내용 추가/삭제 금지, 교정된 텍스트만 출력.\n\n"
    "{text}\n\n"
    "교정:"
)

# 배치 교정용 프롬프트 — 여러 줄을 한 번에 교정한다
_BATCH_CORRECTION_PROMPT: str = (
    "OCR로 인식된 한국어 텍스트입니다. 각 줄의 오타만 교정하세요.\n"
    "규칙: 줄 수와 구조를 그대로 유지, 내용 추가/삭제 금지, "
    "교정된 텍스트만 출력.\n\n"
    "{text}\n\n"
    "교정:"
)

# 교정 대상 최소 길이 (문자 수)
_MIN_CORRECTION_LENGTH: int = 3
# 배치 교정 최대 입력 길이 (문자 수)
_MAX_BATCH_INPUT_CHARS: int = 500


def load_correction_model(
    model_dir: str | Path | None = None,
) -> tuple[Any, Any]:
    """교정용 경량 LLM을 로드한다.

    Qwen3-8B-4bit (mlx-lm)를 사용한다.
    이미 로드된 경우 캐시된 인스턴스를 반환한다.

    Args:
        model_dir: 모델 디렉토리 경로. None이면 기본 경로를 사용한다.

    Returns:
        (model, tokenizer) 튜플
    """
    global _correction_model, _correction_tokenizer

    if _correction_model is not None and _correction_tokenizer is not None:
        return _correction_model, _correction_tokenizer

    try:
        from mlx_lm import load as mlx_load
    except ImportError as exc:
        raise ImportError("mlx-lm 패키지가 필요합니다: pip install mlx-lm") from exc

    if model_dir is None:
        # 기본 모델 경로 — backend/AImodels에서 검색
        base = Path(__file__).resolve().parent.parent.parent / "AImodels"
        candidates = [
            base / "mlx-community--Qwen3-8B-4bit",
        ]
        model_dir = next((p for p in candidates if p.exists()), None)
        if model_dir is None:
            raise FileNotFoundError(
                f"교정 모델을 찾을 수 없습니다: {candidates}"
            )

    logger.info("교정 LLM 로드: %s", model_dir)
    _correction_model, _correction_tokenizer = mlx_load(str(model_dir))
    return _correction_model, _correction_tokenizer


def unload_correction_model() -> None:
    """교정 모델을 메모리에서 해제한다."""
    global _correction_model, _correction_tokenizer
    _correction_model = None
    _correction_tokenizer = None
    gc.collect()
    logger.info("교정 LLM 해제 완료")


def correct_text_with_llm(
    text: str,
    model: Any | None = None,
    tokenizer: Any | None = None,
    max_tokens: int = 512,
) -> str:
    """경량 LLM으로 OCR 텍스트를 교정한다.

    짧은 텍스트(단어/구)는 개별 교정하고,
    긴 텍스트(문장/문단)는 배치 프롬프트로 교정한다.

    Args:
        text: OCR로 인식된 원시 텍스트
        model: mlx-lm 모델 (None이면 자동 로드)
        tokenizer: mlx-lm 토크나이저
        max_tokens: 최대 생성 토큰 수

    Returns:
        교정된 텍스트. LLM 교정 실패 시 원본 반환.
    """
    stripped = text.strip()
    if len(stripped) < _MIN_CORRECTION_LENGTH:
        return text

    if model is None or tokenizer is None:
        model, tokenizer = load_correction_model()

    # 프롬프트 생성
    if len(stripped) > _MAX_BATCH_INPUT_CHARS:
        prompt_text = stripped[:_MAX_BATCH_INPUT_CHARS]
    else:
        prompt_text = stripped

    prompt = _BATCH_CORRECTION_PROMPT.format(text=prompt_text)

    try:
        corrected = _run_mlx_inference(model, tokenizer, prompt, max_tokens)
        # LLM 출력 검증 — 원본과 너무 다르면 원본 유지
        if _is_valid_correction(stripped, corrected):
            return corrected
        logger.debug("교정 결과 검증 실패 — 원본 유지")
        return text
    except Exception as exc:
        logger.warning("LLM 교정 실패: %s", exc)
        return text


def correct_blocks_with_llm(
    texts: list[str],
    model: Any | None = None,
    tokenizer: Any | None = None,
    max_tokens: int = 1024,
) -> list[str]:
    """여러 블록의 텍스트를 한 번의 LLM 호출로 교정한다.

    같은 행의 블록들을 묶어 문맥을 제공하면
    개별 교정보다 정확도가 높다.

    Args:
        texts: 블록별 OCR 텍스트 목록
        model: mlx-lm 모델
        tokenizer: mlx-lm 토크나이저
        max_tokens: 최대 생성 토큰 수

    Returns:
        교정된 텍스트 목록 (입력과 같은 길이)
    """
    if not texts:
        return []

    if model is None or tokenizer is None:
        model, tokenizer = load_correction_model()

    # 짧은 텍스트는 개별 교정 건너뜀
    valid_indices: list[int] = []
    for i, t in enumerate(texts):
        if len(t.strip()) >= _MIN_CORRECTION_LENGTH:
            valid_indices.append(i)

    if not valid_indices:
        return list(texts)

    # 배치로 묶어서 한 번에 교정
    batch_input = "\n".join(texts[i] for i in valid_indices)

    if len(batch_input) > _MAX_BATCH_INPUT_CHARS:
        # 너무 길면 개별 교정
        results = list(texts)
        for i in valid_indices:
            results[i] = correct_text_with_llm(
                texts[i], model, tokenizer, max_tokens=256,
            )
        return results

    prompt = _BATCH_CORRECTION_PROMPT.format(text=batch_input)

    try:
        corrected_batch = _run_mlx_inference(model, tokenizer, prompt, max_tokens)
        corrected_lines = corrected_batch.strip().split("\n")

        # 줄 수가 일치하면 매핑, 아니면 원본 유지
        results = list(texts)
        if len(corrected_lines) == len(valid_indices):
            for idx, corrected_line in zip(valid_indices, corrected_lines):
                line = corrected_line.strip()
                if line and _is_valid_correction(texts[idx].strip(), line):
                    results[idx] = line
        else:
            # 줄 수 불일치 — 개별 교정 폴백
            logger.debug(
                "배치 교정 줄 수 불일치: 기대 %d, 실제 %d",
                len(valid_indices), len(corrected_lines),
            )
            for i in valid_indices:
                results[i] = correct_text_with_llm(
                    texts[i], model, tokenizer, max_tokens=256,
                )
        return results

    except Exception as exc:
        logger.warning("배치 LLM 교정 실패: %s", exc)
        return list(texts)


def _run_mlx_inference(
    model: Any,
    tokenizer: Any,
    prompt: str,
    max_tokens: int,
) -> str:
    """mlx-lm으로 텍스트 생성을 실행한다."""
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    # Qwen3 thinking 모드 비활성화
    messages = [
        {"role": "user", "content": prompt},
    ]
    formatted = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )

    # 탐욕적 디코딩 — 교정은 창의성 불필요
    sampler = make_sampler(temp=0.0)

    result = generate(
        model=model,
        tokenizer=tokenizer,
        prompt=formatted,
        max_tokens=max_tokens,
        sampler=sampler,
        verbose=False,
    )
    return result.strip()


def _is_valid_correction(original: str, corrected: str) -> bool:
    """교정 결과가 유효한지 검증한다.

    LLM이 원본을 과도하게 변형하거나, 내용을 추가/삭제하는 경우를 방지한다.

    Args:
        original: 원본 텍스트 (공백 제거 후)
        corrected: 교정된 텍스트

    Returns:
        True이면 유효한 교정
    """
    if not corrected or not corrected.strip():
        return False

    corrected = corrected.strip()

    # 길이 변화가 30% 이상이면 과도한 변형
    len_ratio = len(corrected) / max(len(original), 1)
    if len_ratio < 0.7 or len_ratio > 1.3:
        return False

    # LLM이 설명을 추가한 경우 감지
    bad_prefixes = ("교정된", "수정된", "다음은", "오타를", "오류를")
    if any(corrected.startswith(p) for p in bad_prefixes):
        return False

    return True
