# OCR 프롬프트 관리 모듈
# mlx-vlm 모델에 전달할 프롬프트 템플릿을 중앙에서 관리한다
# grounding 모드, 표 구조 보존 grounding 모드, 수식 특화 grounding 모드,
# plain text 모드 프롬프트를 제공한다
from __future__ import annotations


class OcrPrompt:
    """OCR 추론에 사용할 프롬프트 템플릿을 제공한다.

    DeepSeek-OCR-2 모델은 네 가지 모드를 지원한다:
    - GROUNDING: 텍스트 + 바운딩 박스 좌표를 함께 출력한다
    - TABLE_GROUNDING: 표 셀을 개별 블록으로 분리하여 구조를 보존한다
    - MATH_GROUNDING: 수식 인식 품질을 높이기 위한 LaTeX 지시 포함 모드
    - PLAIN_TEXT: 텍스트만 추출한다 (좌표 불필요 시 폴백용)
    """

    # grounding 모드 프롬프트 — 텍스트와 정규화 좌표(0~999)를 함께 출력한다
    # <|grounding|> 토큰이 모델의 좌표 출력 모드를 활성화한다
    GROUNDING: str = (
        "<|User|>: <image>\n"
        "<|grounding|>OCR with grounding. "
        "Extract all text and their bounding box coordinates from this image.\n\n"
        "<|Assistant|>:"
    )

    # 표 구조 보존을 위한 향상된 grounding 프롬프트
    # 각 표 셀을 개별 블록으로 출력하고, 행·열 순서를 명시적으로 처리하도록 지시한다
    # 빈 셀, 셀 경계, 셀 병합 금지 지시를 포함하여 표 구조 완전성을 높인다
    TABLE_GROUNDING: str = (
        "<|User|>: <image>\n"
        "<|grounding|>OCR with grounding. "
        "Extract all text and their bounding box coordinates from this image.\n"
        "For tables: output each cell as a separate text block with its own bounding box. "
        "Use block_type 'table_header' for header cells, 'table_cell' for data cells. "
        "Process table cells row by row, left to right. "
        "For empty cells, output a single space as text. "
        "Each cell must have its own bounding box. "
        "Do not merge adjacent cells into one block.\n\n"
        "<|Assistant|>:"
    )

    # 수식 인식 특화 grounding 프롬프트
    # 분수·첨자·적분 기호 등 LaTeX 표기법을 명시적으로 지시하여 수식 완성도를 높인다
    # 중괄호 닫기, \frac{}{}, _{}, ^{} 등의 올바른 LaTeX 구조를 강제한다
    MATH_GROUNDING: str = (
        "<|User|>: <image>\n"
        "<|grounding|>OCR with grounding. "
        "Extract all text and their bounding box coordinates from this image.\n"
        "For mathematical formulas: use standard LaTeX notation. "
        "Wrap fractions with \\frac{}{}, subscripts with _{}, superscripts with ^{}. "
        "Use \\sum, \\int, \\prod for operators. "
        "Ensure all braces are properly closed.\n\n"
        "<|Assistant|>:"
    )

    # plain text 폴백 프롬프트 — 좌표 없이 텍스트만 추출한다
    # grounding 파싱 실패 시 이 프롬프트로 재시도한다
    PLAIN_TEXT: str = (
        "<image>\n"
        "Read the text in this image. "
        "Print only the text, exactly as it appears, line by line. "
        "Do not use markdown. Do not use #, *, **, |, or ---. "
        "Do not write any explanation or repeat these instructions."
    )

    @classmethod
    def get_grounding(cls) -> str:
        """grounding 모드 프롬프트를 반환한다."""
        return cls.GROUNDING

    @classmethod
    def get_table_grounding(cls) -> str:
        """표 구조 보존 grounding 프롬프트를 반환한다."""
        return cls.TABLE_GROUNDING

    @classmethod
    def get_math_grounding(cls) -> str:
        """수식 인식 특화 grounding 프롬프트를 반환한다.

        LaTeX 표기법 지시가 포함되어 있어 분수·첨자·적분 등
        수식이 많은 이미지 처리 시 인식 품질을 높인다.
        """
        return cls.MATH_GROUNDING

    @classmethod
    def get_plain_text(cls) -> str:
        """plain text 폴백 프롬프트를 반환한다."""
        return cls.PLAIN_TEXT

    @classmethod
    def get_default(cls) -> str:
        """기본 프롬프트를 반환한다 (grounding 모드)."""
        return cls.GROUNDING
