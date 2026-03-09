# 앙상블 투표 모듈
# 3개 후처리 모델의 독립 교정 결과를 비교하여 최종 텍스트를 결정한다
#
# 투표 규칙:
#   1. 3개 일치 → 그대로 채택
#   2. 2개 일치 → 다수결 채택
#   3. 3개 모두 다름 → 콘텐츠 타입별 전문 모델 우선
#   4. 고유명사 사전 매칭 → 무조건 채택
from __future__ import annotations

import difflib
from dataclasses import dataclass

from backend.ocr.atoms.classify_content import ContentType, classify_text
from backend.ocr.atoms.domain_dictionary import load_domain_dictionary


@dataclass
class EnsembleResult:
    """앙상블 투표 결과를 담는 데이터 컨테이너다."""
    text: str               # 최종 선택된 텍스트
    source: str             # 선택 근거 ("unanimous", "majority", "specialist", "dictionary")
    content_type: ContentType  # 텍스트의 주요 콘텐츠 타입


# ── 콘텐츠 타입별 전문 모델 우선순위 ────────────────────────────────────────
# 3개 모두 다를 때 어떤 모델의 결과를 채택할지 결정한다
# 인덱스: 0=Qwen3(한국어·영어), 1=EXAONE(한국어 고유명사), 2=DeepSeek-R1(수학·코드·표)
_SPECIALIST_INDEX: dict[ContentType, int] = {
    ContentType.KOREAN: 1,    # EXAONE — 한국어 네이티브
    ContentType.ENGLISH: 0,   # Qwen3 — 다국어 최강
    ContentType.MATH: 2,      # DeepSeek-R1 — 추론 특화
    ContentType.CODE: 2,      # DeepSeek-R1 — 코드 이해
    ContentType.TABLE: 2,     # DeepSeek-R1 — 구조 추론
    ContentType.MIXED: 1,     # EXAONE — 한국어 기본
}


def ensemble_vote(
    version_a: str,
    version_b: str,
    version_c: str,
    original: str,
) -> EnsembleResult:
    """3개 모델의 교정 결과를 앙상블 투표로 병합한다.

    Args:
        version_a: Qwen3 교정 결과
        version_b: EXAONE 교정 결과
        version_c: DeepSeek-R1 교정 결과
        original: OCR 원본 텍스트 (폴백용)

    Returns:
        투표 결과 (최종 텍스트, 선택 근거, 콘텐츠 타입)
    """
    content_type = classify_text(original)

    # 도메인 사전 기반 고유명사 교정 — 최우선 적용
    domain_dict = _get_cached_domain_dict()

    # 줄 단위 투표로 최적 결과를 조합한다
    final_lines: list[str] = []
    source_counts: dict[str, int] = {
        "unanimous": 0, "majority": 0, "specialist": 0, "dictionary": 0,
    }

    lines_a = version_a.split("\n")
    lines_b = version_b.split("\n")
    lines_c = version_c.split("\n")
    lines_orig = original.split("\n")

    # 최대 줄 수에 맞춰 정렬 — 줄 수가 다르면 빈 줄로 패딩
    max_lines = max(len(lines_a), len(lines_b), len(lines_c), len(lines_orig))

    for i in range(max_lines):
        la = lines_a[i] if i < len(lines_a) else ""
        lb = lines_b[i] if i < len(lines_b) else ""
        lc = lines_c[i] if i < len(lines_c) else ""
        lo = lines_orig[i] if i < len(lines_orig) else ""

        line, source = _vote_single_line(la, lb, lc, lo, content_type, domain_dict)
        final_lines.append(line)
        source_counts[source] = source_counts.get(source, 0) + 1

    # 가장 많이 사용된 소스를 대표 근거로 설정
    dominant_source = max(source_counts, key=lambda k: source_counts[k])

    return EnsembleResult(
        text="\n".join(final_lines),
        source=dominant_source,
        content_type=content_type,
    )


def _vote_single_line(
    line_a: str,
    line_b: str,
    line_c: str,
    line_orig: str,
    content_type: ContentType,
    domain_dict: frozenset[str],
) -> tuple[str, str]:
    """단일 줄에 대해 투표를 수행한다.

    Args:
        line_a: Qwen3 결과
        line_b: EXAONE 결과
        line_c: DeepSeek-R1 결과
        line_orig: 원본 텍스트
        content_type: 전체 문서의 콘텐츠 타입
        domain_dict: 도메인 사전

    Returns:
        (선택된 줄, 선택 근거)
    """
    sa = line_a.strip()
    sb = line_b.strip()
    sc = line_c.strip()

    # 빈 줄은 그대로 반환
    if not sa and not sb and not sc:
        return line_orig, "unanimous"

    # 1. 3개 일치 → 만장일치 채택
    if sa == sb == sc:
        return line_a, "unanimous"

    # 2. 도메인 사전 매칭 — 사전에 있는 단어가 포함된 버전을 우선
    dict_result = _check_dictionary_match(line_a, line_b, line_c, domain_dict)
    if dict_result is not None:
        return dict_result, "dictionary"

    # 3. 다수결 — 2개 일치 시 채택
    if sa == sb:
        return line_a, "majority"
    if sa == sc:
        return line_a, "majority"
    if sb == sc:
        return line_b, "majority"

    # 4. 3개 모두 다름 → 콘텐츠 타입별 전문 모델 우선
    specialist_idx = _SPECIALIST_INDEX.get(content_type, 1)
    versions = [line_a, line_b, line_c]
    return versions[specialist_idx], "specialist"


def _check_dictionary_match(
    line_a: str,
    line_b: str,
    line_c: str,
    domain_dict: frozenset[str],
) -> str | None:
    """3개 버전 중 도메인 사전 매칭이 가장 많은 버전을 반환한다.

    매칭 수가 동일하면 None을 반환하여 다른 규칙으로 폴백한다.

    Args:
        line_a: Qwen3 결과
        line_b: EXAONE 결과
        line_c: DeepSeek-R1 결과
        domain_dict: 도메인 사전

    Returns:
        가장 많은 사전 매칭을 가진 줄, 또는 None
    """
    if not domain_dict:
        return None

    scores = [
        _count_dict_matches(line_a, domain_dict),
        _count_dict_matches(line_b, domain_dict),
        _count_dict_matches(line_c, domain_dict),
    ]

    max_score = max(scores)
    if max_score == 0:
        return None

    # 최고 점수가 유일한 경우에만 채택
    top_indices = [i for i, s in enumerate(scores) if s == max_score]
    if len(top_indices) != 1:
        return None

    versions = [line_a, line_b, line_c]
    return versions[top_indices[0]]


def _count_dict_matches(line: str, domain_dict: frozenset[str]) -> int:
    """줄에서 도메인 사전에 매칭되는 단어 수를 세어 반환한다."""
    count = 0
    for term in domain_dict:
        if len(term) >= 2 and term in line:
            count += 1
    return count


# ── 도메인 사전 캐시 ─────────────────────────────────────────────────────────
_cached_domain_dict: frozenset[str] | None = None


def _get_cached_domain_dict() -> frozenset[str]:
    """도메인 사전을 지연 로드하여 캐시된 결과를 반환한다."""
    global _cached_domain_dict
    if _cached_domain_dict is None:
        try:
            _cached_domain_dict = load_domain_dictionary()
        except Exception:
            _cached_domain_dict = frozenset()
    return _cached_domain_dict
