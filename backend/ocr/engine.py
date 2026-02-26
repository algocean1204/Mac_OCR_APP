# OCR 추론 엔진 모듈
# mlx-vlm 모델을 로드하고 이미지에서 텍스트를 추출한다
# Apple Silicon MPS를 네이티브로 활용하여 OCR 추론을 수행한다
from __future__ import annotations

import signal
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import ModelError, OcrProcessingError
from backend.ocr.grounding_parser import OcrBlock, parse_grounding_output
from backend.ocr.prompt import OcrPrompt
from backend.ocr.text_cleaner import clean_text
from backend.progress.reporter import ProgressReporter


class OcrEngine:
    """mlx-vlm 모델을 사용하여 이미지에서 텍스트를 추출하는 OCR 엔진이다."""

    def __init__(
        self,
        reporter: ProgressReporter,
        max_tokens: int,
        max_image_size: int,
    ) -> None:
        self._reporter: ProgressReporter = reporter
        # 설정에서 주입받은 추론 파라미터
        self._max_tokens: int = max_tokens
        self._max_image_size: int = max_image_size
        # 모델과 프로세서는 load_model() 호출 후 초기화된다
        self._model: Any | None = None
        self._processor: Any | None = None
        self._is_loaded: bool = False

    def load_model(self, model_id: str, model_dir: Path | None = None) -> None:
        """mlx-vlm 모델과 프로세서를 메모리에 로드한다.

        Args:
            model_id: HuggingFace 모델 ID 또는 로컬 경로
            model_dir: 로컬 캐시 디렉토리 (None이면 model_id를 직접 사용)

        Raises:
            ModelError: 모델 로드 실패 시
        """
        self._reporter.report_log("info", f"모델 로드 시작: {model_id}")

        try:
            from mlx_vlm import load as mlx_load
        except ImportError as exc:
            raise ModelError(
                code=ErrorCodes.MODEL_INCOMPATIBLE,
                detail="mlx-vlm 패키지가 설치되지 않음",
            ) from exc

        # 로컬 디렉토리가 있으면 해당 경로를, 없으면 모델 ID를 직접 사용한다
        load_path = str(model_dir) if model_dir and model_dir.exists() else model_id

        try:
            self._model, self._processor = mlx_load(
                load_path,
                trust_remote_code=True,
            )
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
    ) -> list[OcrBlock] | str:
        """이미지에서 OCR을 실행한다. grounding 모드 우선, 실패 시 plain text 폴백.

        Args:
            image: PIL Image 객체 (페이지 이미지)
            timeout_seconds: 추론 타임아웃 (초)

        Returns:
            grounding 파싱 성공 시 OcrBlock 리스트,
            파싱 실패(폴백) 시 정제된 텍스트 문자열

        Raises:
            OcrProcessingError: OCR 실패 또는 타임아웃 시
        """
        if not self._is_loaded:
            raise OcrProcessingError(
                code=ErrorCodes.OCR_PAGE_FAILED,
                detail="모델이 로드되지 않은 상태에서 OCR 호출됨",
            )

        # 이미지 크기를 제한하여 메모리 과다 사용을 방지한다
        resized_image = _resize_if_needed(image, self._max_image_size)

        try:
            # 1단계: grounding 프롬프트로 추론한다
            raw = self._run_inference_with_timeout(
                resized_image, timeout_seconds, OcrPrompt.get_grounding()
            )

            # 2단계: grounding 출력을 파싱하여 블록 목록을 얻는다
            blocks = parse_grounding_output(raw)
            if blocks:
                return blocks

            # 3단계: 블록이 없으면 plain text 프롬프트로 재시도한다
            raw_plain = self._run_inference_with_timeout(
                resized_image, timeout_seconds, OcrPrompt.get_plain_text()
            )
            return clean_text(raw_plain)

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
            # 크기 조정된 임시 이미지는 즉시 해제한다
            if resized_image is not image:
                resized_image.close()

    def _run_inference_with_timeout(
        self,
        image: Image.Image,
        timeout_seconds: int,
        prompt: str,
    ) -> str:
        """지정된 프롬프트로 타임아웃 시그널을 이용해 추론을 실행한다.

        mlx_vlm.generate는 이미지 파일 경로(str)를 받으므로
        PIL Image를 임시 파일에 저장한 뒤 경로를 전달한다.

        Args:
            image: PIL Image 객체
            timeout_seconds: SIGALRM 타임아웃 (초)
            prompt: 모델에 전달할 프롬프트 문자열
        """
        from mlx_vlm import generate as mlx_generate

        # SIGALRM을 이용하여 타임아웃을 구현한다 (Unix 전용)
        def _timeout_handler(signum: int, frame: object) -> None:
            raise TimeoutError()

        original_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)

        # tmp_path를 finally 블록에서 참조하기 위해 미리 선언한다
        tmp_path: str = ""

        try:
            # PIL Image를 임시 PNG 파일로 저장하여 경로를 전달한다
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp, format="PNG")
                tmp_path = tmp.name

            # mlx_vlm.generate 시그니처: (model, processor, prompt, image=path_str)
            gen_result = mlx_generate(
                self._model,
                self._processor,
                prompt,
                image=tmp_path,
                max_tokens=self._max_tokens,
                verbose=False,
            )
            # GenerationResult 데이터클래스에서 텍스트를 추출한다
            result: str = (
                gen_result.text if hasattr(gen_result, "text") else str(gen_result)
            )
        finally:
            # 타임아웃 알람을 해제하고 원래 핸들러를 복원한다
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original_handler)
            # 임시 파일 정리
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        return result

    def is_loaded(self) -> bool:
        """모델이 로드되어 있는지 여부를 반환한다."""
        return self._is_loaded


def _resize_if_needed(image: Image.Image, max_image_size: int) -> Image.Image:
    """이미지가 최대 크기를 초과하면 비율을 유지하며 축소한다.

    Args:
        image: 원본 PIL Image 객체
        max_image_size: 허용할 최대 픽셀 크기 (가로/세로 중 긴 변 기준)
    """
    width, height = image.size
    if width <= max_image_size and height <= max_image_size:
        return image

    # 가장 긴 변을 기준으로 비율을 계산한다
    ratio = max_image_size / max(width, height)
    new_width = int(width * ratio)
    new_height = int(height * ratio)

    return image.resize((new_width, new_height), Image.LANCZOS)
