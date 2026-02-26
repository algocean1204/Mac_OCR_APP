# OCR 엔진 패키지 — mlx-vlm 모델 로드와 추론을 담당한다
from backend.ocr.engine import OcrEngine
from backend.ocr.grounding_parser import OcrBlock, parse_grounding_output
from backend.ocr.prompt import OcrPrompt
from backend.ocr.text_cleaner import clean_text

__all__ = ["OcrEngine", "OcrBlock", "OcrPrompt", "clean_text", "parse_grounding_output"]
