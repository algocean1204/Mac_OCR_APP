# OCR 프롬프트 관리 모듈
# GLM-OCR 모델에 전달할 프롬프트 텍스트를 중앙에서 관리한다
# transformers의 chat template을 통해 메시지로 변환된다
from __future__ import annotations


class OcrPrompt:
    """OCR 추론에 사용할 프롬프트 텍스트를 제공한다.

    GLM-OCR 모델은 transformers의 chat template을 사용하며,
    프롬프트 텍스트는 메시지의 text 부분으로 전달된다.
    """

    # 기본 OCR 프롬프트 — 이미지의 모든 텍스트를 정확히 추출한다
    GROUNDING: str = (
        "OCR this image. Extract all text exactly as it appears, line by line. "
        "Preserve the original layout and structure. "
        "Do not add any explanation or commentary."
    )

    # 표 구조 보존 프롬프트 — 표의 행·열 구조를 유지하며 추출한다
    TABLE_GROUNDING: str = (
        "OCR this image. Extract all text exactly as it appears. "
        "For tables, preserve the row and column structure. "
        "Output each row on a separate line, separating cells with tabs. "
        "Do not add any explanation or commentary."
    )

    # 수식 인식 특화 프롬프트 — LaTeX 표기법으로 수식을 출력한다
    MATH_GROUNDING: str = (
        "OCR this image. Extract all text exactly as it appears. "
        "For mathematical formulas, use standard LaTeX notation. "
        "Wrap fractions with \\frac{}{}, subscripts with _{}, superscripts with ^{}. "
        "Do not add any explanation or commentary."
    )

    # plain text 폴백 프롬프트 — 단순 텍스트 추출
    PLAIN_TEXT: str = (
        "Read the text in this image. "
        "Print only the text, exactly as it appears, line by line. "
        "Do not use markdown. Do not use #, *, **, |, or ---. "
        "Do not write any explanation or repeat these instructions."
    )

    @classmethod
    def get_grounding(cls) -> str:
        """기본 OCR 프롬프트를 반환한다."""
        return cls.GROUNDING

    @classmethod
    def get_table_grounding(cls) -> str:
        """표 구조 보존 프롬프트를 반환한다."""
        return cls.TABLE_GROUNDING

    @classmethod
    def get_math_grounding(cls) -> str:
        """수식 인식 특화 프롬프트를 반환한다."""
        return cls.MATH_GROUNDING

    @classmethod
    def get_plain_text(cls) -> str:
        """plain text 폴백 프롬프트를 반환한다."""
        return cls.PLAIN_TEXT

    @classmethod
    def get_default(cls) -> str:
        """기본 프롬프트를 반환한다."""
        return cls.GROUNDING
