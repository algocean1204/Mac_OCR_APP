# OCR 후처리 엔진 모듈
# mlx-lm 또는 transformers(torch) 텍스트 모델을 로드하여
# OCR 출력의 교정을 수행한다.
#
# 앙상블 파이프라인 설계:
#   OCR(GLM-OCR) → 언로드 → Qwen3(korean) + EXAONE(proper_noun) + DeepSeek-R1(reasoning)
#   3개 모델이 각각 독립적으로 원본을 교정 → 앙상블 투표로 최종 결과 결정
#   각 모델은 순차 로드/교정/언로드하여 메모리를 공유하지 않는다.
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

from backend.config.model_registry import ModelFramework, get_model_spec_by_id
from backend.ocr.atoms.build_refine_prompt import (
    build_korean_refine_prompt,
    build_proper_noun_prompt,
    build_reasoning_verify_prompt,
    should_refine,
)
from backend.ocr.atoms.chunk_text import chunk_text_for_refinement
from backend.ocr.atoms.parse_refined_text import parse_refined_output


# 후처리 LLM의 최대 생성 토큰 수 — 입력 텍스트와 비슷한 길이의 교정 결과를 기대한다
_POST_MAX_TOKENS: int = 2048

# 후처리 생성 온도 — 낮을수록 결정론적 출력 (교정 목적이므로 낮게 설정)
_POST_TEMPERATURE: float = 0.1

# 후처리 Top-P — 다양성을 최소화하여 원본에 가까운 출력을 유도한다
_POST_TOP_P: float = 0.9


class PostProcessor:
    """텍스트 모델을 사용하여 OCR 출력을 후처리하는 엔진이다.

    mlx-lm(MLX_LM) 또는 transformers+torch(TRANSFORMERS_LM) 프레임워크를
    모델 레지스트리 설정에 따라 자동 감지하여 로드한다.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._is_loaded: bool = False
        self._model_id: str = ""
        self._framework: ModelFramework | None = None

    def load_model(self, model_id: str, model_dir: Path | None = None) -> None:
        """텍스트 모델과 토크나이저를 메모리에 로드한다.

        모델 레지스트리에서 프레임워크를 자동 감지하여
        mlx-lm 또는 transformers+torch로 로드한다.

        Args:
            model_id: HuggingFace 모델 ID 또는 로컬 경로
            model_dir: 로컬 캐시 디렉토리 (None이면 model_id를 직접 사용)

        Raises:
            RuntimeError: 모델 로드 실패 시
        """
        spec = get_model_spec_by_id(model_id)
        framework = spec.framework if spec else ModelFramework.MLX_LM

        load_path = str(model_dir) if model_dir and model_dir.exists() else model_id

        if framework == ModelFramework.TRANSFORMERS_LM:
            self._load_torch_model(model_id, load_path)
        else:
            self._load_mlx_model(model_id, load_path)

        self._framework = framework

    def _load_mlx_model(self, model_id: str, load_path: str) -> None:
        """mlx-lm 프레임워크로 모델을 로드한다."""
        try:
            from mlx_lm import load as mlx_lm_load
        except ImportError as exc:
            raise RuntimeError(
                "mlx-lm 패키지가 설치되지 않음 — pip install mlx-lm"
            ) from exc

        try:
            import os
            os.environ["HF_HUB_TRUST_REMOTE_CODE"] = "1"
            self._model, self._tokenizer = mlx_lm_load(load_path)
            self._is_loaded = True
            self._model_id = model_id
        except Exception as exc:
            raise RuntimeError(f"후처리 모델(MLX) 로드 실패: {exc}") from exc

    def _load_torch_model(self, model_id: str, load_path: str) -> None:
        """transformers + torch 프레임워크로 모델을 로드한다.

        KORMo 등 커스텀 아키텍처 모델은 trust_remote_code를 활성화한다.
        Apple Silicon MPS 가속을 사용한다.
        """
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "transformers/torch 패키지가 설치되지 않음"
            ) from exc

        try:
            # MPS(Metal) 가속 필수 — Apple Silicon 환경에서만 동작한다
            if not torch.backends.mps.is_available():
                raise RuntimeError("MPS 가속이 필요합니다 (Apple Silicon 전용)")
            device = torch.device("mps")

            self._tokenizer = AutoTokenizer.from_pretrained(
                load_path, trust_remote_code=True,
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                load_path,
                trust_remote_code=True,
                dtype=torch.bfloat16,
            ).to(device)

            self._is_loaded = True
            self._model_id = model_id
        except Exception as exc:
            raise RuntimeError(f"후처리 모델(torch) 로드 실패: {exc}") from exc

    def refine_text(self, text: str, mode: str = "korean") -> str:
        """단일 텍스트 문자열에 후처리를 적용한다.

        Args:
            text: OCR로 추출된 텍스트
            mode: 후처리 모드 — "korean", "proper_noun", 또는 "reasoning"

        Returns:
            교정된 텍스트, 실패 시 원본
        """
        if not self._is_loaded or not should_refine(text):
            return text

        return self._generate_refinement(text, mode)

    def _generate_refinement(self, text: str, mode: str) -> str:
        """LLM을 호출하여 텍스트 교정을 수행한다.

        프레임워크에 따라 mlx-lm 또는 torch 추론 경로를 선택한다.
        텍스트가 긴 경우 청크 분할 후 개별 교정하고 결과를 합산한다.

        Args:
            text: 교정 대상 텍스트
            mode: "korean" 또는 "reasoning"

        Returns:
            교정된 텍스트, 오류 시 원본
        """
        chunks = chunk_text_for_refinement(text)
        if not chunks:
            return text

        refined_chunks: list[str] = []
        for chunk in chunks:
            refined_chunk = self._refine_single_chunk(chunk, mode)
            refined_chunks.append(refined_chunk)

        return "\n".join(refined_chunks) if len(refined_chunks) > 1 else refined_chunks[0]

    def _estimate_max_tokens(self, text: str) -> int:
        """입력 텍스트 길이에 기반하여 동적 max_tokens를 계산한다.

        토크나이저로 입력 토큰 수를 측정하고, 출력이 입력보다 약간 길 수 있음을
        고려하여 1.3배 + 여유분 50 토큰을 할당한다.
        고정 2048 대비 평균 60-75% 토큰 절약 효과가 있다.

        Args:
            text: 입력 텍스트 (프롬프트 포함 전 원본)

        Returns:
            동적으로 계산된 max_tokens (128 이상, _POST_MAX_TOKENS 이하)
        """
        if self._tokenizer is None:
            return _POST_MAX_TOKENS
        try:
            input_tokens = len(self._tokenizer.encode(text))
        except Exception:
            # 토크나이저 인코딩 실패 시 문자 수 기반 추정 (한국어 평균 1.5토큰/자)
            input_tokens = int(len(text) * 1.5)
        estimated = int(input_tokens * 1.3) + 50
        return max(128, min(estimated, _POST_MAX_TOKENS))

    def _refine_single_chunk(self, chunk: str, mode: str) -> str:
        """단일 청크에 대해 LLM 교정을 수행한다.

        Args:
            chunk: 교정 대상 텍스트 청크
            mode: "korean" 또는 "reasoning"

        Returns:
            교정된 청크 텍스트, 오류 시 원본 청크
        """
        if mode == "reasoning":
            prompt = build_reasoning_verify_prompt(chunk)
        elif mode == "proper_noun":
            prompt = build_proper_noun_prompt(chunk)
        else:
            prompt = build_korean_refine_prompt(chunk)

        # 입력 길이에 비례하여 max_tokens를 동적 조정한다
        max_tokens = self._estimate_max_tokens(chunk)

        try:
            if self._framework == ModelFramework.TRANSFORMERS_LM:
                raw_output = self._generate_torch(prompt, max_tokens)
            else:
                raw_output = self._generate_mlx(prompt, max_tokens)

            return parse_refined_output(raw_output, chunk)
        except Exception:
            return chunk

    def _generate_mlx(self, prompt: str, max_tokens: int = _POST_MAX_TOKENS) -> str:
        """mlx-lm으로 텍스트를 생성한다.

        Qwen3 계열 모델은 thinking 모드를 비활성화하여
        불필요한 사고 과정 생성을 방지한다.

        Args:
            prompt: LLM에 전달할 프롬프트
            max_tokens: 최대 생성 토큰 수 (동적 조정됨)
        """
        from mlx_lm import generate as mlx_lm_generate
        from mlx_lm.sample_utils import make_sampler

        sampler = make_sampler(temp=_POST_TEMPERATURE, top_p=_POST_TOP_P)

        # chat template 적용 — thinking 비활성화 (Qwen3 등)
        formatted_prompt = self._format_chat_prompt(prompt)

        return mlx_lm_generate(
            self._model,
            self._tokenizer,
            prompt=formatted_prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False,
        )

    def _format_chat_prompt(self, prompt: str) -> str:
        """토크나이저의 chat template을 적용하여 프롬프트를 포맷한다.

        Qwen3 계열: enable_thinking=False로 thinking 모드를 비활성화한다.
        DeepSeek-R1 계열: 빈 thinking 블록을 프리필하여 사고 과정 생성을 억제한다.
        chat template이 없으면 원본 프롬프트를 그대로 반환한다.
        """
        if self._tokenizer is None or not hasattr(self._tokenizer, "apply_chat_template"):
            return prompt

        messages = [{"role": "user", "content": prompt}]

        try:
            # Qwen3는 enable_thinking=False로 사고 과정 출력을 억제한다
            formatted = self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
                enable_thinking=False,
            )
        except TypeError:
            # enable_thinking 미지원 모델 — 기본 chat template 적용
            try:
                formatted = self._tokenizer.apply_chat_template(
                    messages,
                    add_generation_prompt=True,
                    tokenize=False,
                )
            except Exception:
                return prompt

        # DeepSeek-R1 계열: 빈 <think> 블록을 프리필하여 사고 과정 생성을 건너뛴다
        # 이렇게 하면 모델이 thinking이 완료된 것으로 인식하고 바로 답변을 생성한다
        if "deepseek" in self._model_id.lower() and "r1" in self._model_id.lower():
            formatted += "<think>\n</think>\n\n"

        return formatted

    def _generate_torch(self, prompt: str, max_tokens: int = _POST_MAX_TOKENS) -> str:
        """transformers + torch로 텍스트를 생성한다.

        KORMo 등 커스텀 아키텍처 모델의 추론에 사용한다.
        chat template을 적용하여 모델에 맞는 프롬프트 형식을 생성한다.

        Args:
            prompt: LLM에 전달할 프롬프트
            max_tokens: 최대 생성 토큰 수 (동적 조정됨)
        """
        import torch

        device = next(self._model.parameters()).device

        # chat template 적용
        formatted_prompt = self._format_torch_chat_prompt(prompt)

        inputs = self._tokenizer(
            formatted_prompt, return_tensors="pt", truncation=True, max_length=4096,
        ).to(device)

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=_POST_TEMPERATURE,
                top_p=_POST_TOP_P,
                do_sample=True,
            )

        # 입력 토큰을 제외하고 생성된 토큰만 디코딩한다
        input_len = inputs["input_ids"].shape[1]
        return self._tokenizer.decode(
            outputs[0][input_len:], skip_special_tokens=True,
        )

    def _format_torch_chat_prompt(self, prompt: str) -> str:
        """torch 모델용 chat template을 적용한다.

        chat template이 없으면 원본 프롬프트를 그대로 반환한다.
        """
        if self._tokenizer is None or not hasattr(self._tokenizer, "apply_chat_template"):
            return prompt

        messages = [{"role": "user", "content": prompt}]

        try:
            formatted = self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
            return formatted
        except Exception:
            return prompt

    def unload(self) -> None:
        """로드된 모델을 메모리에서 해제한다."""
        self._model = None
        self._tokenizer = None
        self._is_loaded = False
        self._model_id = ""
        self._framework = None

        gc.collect()

        # MLX 캐시 정리
        try:
            import mlx.core as mx
            mx.clear_cache()
        except (ImportError, AttributeError):
            pass

        # torch MPS 캐시 정리
        try:
            import torch
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except (ImportError, AttributeError, RuntimeError):
            pass

    def is_loaded(self) -> bool:
        """모델이 로드되어 있는지 여부를 반환한다."""
        return self._is_loaded

    @property
    def model_id(self) -> str:
        """현재 로드된 모델의 ID를 반환한다."""
        return self._model_id
