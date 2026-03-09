# OCR 추론 엔진 모듈
# transformers + torch 모델을 로드하고 이미지에서 텍스트를 추출한다
# Apple Silicon MPS를 활용하여 OCR 추론을 수행한다
from __future__ import annotations

import signal
from typing import Any

import torch
from PIL import Image

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import ModelError, OcrProcessingError
from backend.ocr.prompt import OcrPrompt
from backend.ocr.text_cleaner import clean_text
from backend.progress.reporter import ProgressReporter


class OcrEngine:
    """transformers 모델을 사용하여 이미지에서 텍스트를 추출하는 OCR 엔진이다."""

    def __init__(
        self,
        reporter: ProgressReporter,
        max_tokens: int,
        max_image_size: int,
    ) -> None:
        self._reporter: ProgressReporter = reporter
        self._max_tokens: int = max_tokens
        self._max_image_size: int = max_image_size
        self._model: Any | None = None
        self._processor: Any | None = None
        self._device: torch.device | None = None
        self._is_loaded: bool = False

    def load_model(self, model_id: str, model_dir: "str | None" = None) -> None:
        """transformers 모델과 프로세서를 메모리에 로드한다.

        Args:
            model_id: HuggingFace 모델 ID 또는 로컬 경로
            model_dir: 로컬 캐시 디렉토리 (None이면 model_id를 직접 사용)

        Raises:
            ModelError: 모델 로드 실패 시
        """
        self._reporter.report_log("info", f"모델 로드 시작: {model_id}")

        try:
            from transformers import AutoModelForImageTextToText, Glm46VProcessor
        except ImportError as exc:
            raise ModelError(
                code=ErrorCodes.MODEL_INCOMPATIBLE,
                detail="transformers 패키지가 설치되지 않음",
            ) from exc

        load_path = model_dir if model_dir else model_id
        self._device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

        try:
            self._processor = Glm46VProcessor.from_pretrained(load_path)
            self._model = AutoModelForImageTextToText.from_pretrained(
                pretrained_model_name_or_path=load_path,
                dtype=torch.bfloat16,
            ).to(self._device)
            self._is_loaded = True
        except Exception as exc:
            raise ModelError(
                code=ErrorCodes.MODEL_LOAD_FAILED,
                detail=f"모델 로드 실패: {exc}",
            ) from exc

        self._reporter.report_log("info", "모델 로드 완료")

    def run_ocr(
        self,
        image: Image.Image,
        timeout_seconds: int = 120,
    ) -> str:
        """이미지에서 OCR을 실행하여 텍스트를 반환한다.

        Args:
            image: PIL Image 객체 (페이지 이미지)
            timeout_seconds: 추론 타임아웃 (초)

        Returns:
            정제된 텍스트 문자열

        Raises:
            OcrProcessingError: OCR 실패 또는 타임아웃 시
        """
        if not self._is_loaded:
            raise OcrProcessingError(
                code=ErrorCodes.OCR_PAGE_FAILED,
                detail="모델이 로드되지 않은 상태에서 OCR 호출됨",
            )

        resized_image = _resize_if_needed(image, self._max_image_size)

        try:
            raw = self._run_inference_with_timeout(
                resized_image, timeout_seconds, OcrPrompt.get_grounding()
            )
            return clean_text(raw)

        except TimeoutError as exc:
            raise OcrProcessingError(
                code=ErrorCodes.OCR_TIMEOUT,
                detail=f"OCR 추론이 {timeout_seconds}초를 초과함",
            ) from exc
        except Exception as exc:
            raise OcrProcessingError(
                code=ErrorCodes.OCR_PAGE_FAILED,
                detail=f"OCR 추론 실패: {exc}",
            ) from exc
        finally:
            if resized_image is not image:
                resized_image.close()

    def _run_inference_with_timeout(
        self,
        image: Image.Image,
        timeout_seconds: int,
        prompt: str,
    ) -> str:
        """지정된 프롬프트로 타임아웃 시그널을 이용해 추론을 실행한다.

        Args:
            image: PIL Image 객체
            timeout_seconds: SIGALRM 타임아웃 (초)
            prompt: 모델에 전달할 프롬프트 문자열
        """
        def _timeout_handler(signum: int, frame: object) -> None:
            raise TimeoutError()

        original_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)

        try:
            return _run_glm_ocr_inference(
                self._model, self._processor, self._device,
                image, prompt, self._max_tokens,
            )
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original_handler)

    def is_loaded(self) -> bool:
        """모델이 로드되어 있는지 여부를 반환한다."""
        return self._is_loaded


def _run_glm_ocr_inference(
    model: Any,
    processor: Any,
    device: torch.device,
    image: Image.Image,
    prompt: str,
    max_tokens: int,
) -> str:
    """GLM-OCR 모델로 추론을 실행하고 텍스트를 반환한다.

    Args:
        model: 로드된 transformers 모델 인스턴스
        processor: 로드된 AutoProcessor 인스턴스
        device: torch 장치 (mps 또는 cpu)
        image: PIL Image 객체
        prompt: OCR 프롬프트 문자열
        max_tokens: 최대 생성 토큰 수

    Returns:
        모델 출력 텍스트
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

    # 프로세서로 입력 텐서 생성
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(device)

    # 추론 실행
    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=max_tokens)

    # 입력 토큰을 제외하고 생성된 토큰만 디코딩한다
    input_len = inputs["input_ids"].shape[1]
    result: str = processor.decode(
        outputs[0][input_len:], skip_special_tokens=True,
    )
    return result


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
