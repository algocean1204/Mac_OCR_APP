# 도메인 용어 사전 로더 모듈
# IT/통계/빅데이터 분야 용어를 텍스트 파일에서 불러와
# O(1) 멤버십 검사가 가능한 집합(set)으로 제공한다.
from __future__ import annotations

from pathlib import Path

# 기본 사전 파일 경로 — 이 모듈 위치 기준 상위 data 폴더
_DEFAULT_DICT_PATH: Path = Path(__file__).parent.parent / "data" / "default_terms.txt"

# 복합어 사전 파일 경로 — 기본 용어들의 조합어를 담은 보조 사전
_COMPOUND_DICT_PATH: Path = Path(__file__).parent.parent / "data" / "compound_terms.txt"


def load_domain_dictionary(dict_path: str | Path | None = None) -> frozenset[str]:
    """도메인 용어 사전을 파일에서 읽어 불변 집합으로 반환한다.

    기본 사전(default_terms.txt)과 복합어 사전(compound_terms.txt)을
    함께 로드하여 합산한 결과를 반환한다.
    사용자 지정 경로를 제공하면 해당 파일만 사용하고 복합어 사전은 추가하지 않는다.

    파일은 한 줄에 용어 하나를 포함해야 한다.
    '#'으로 시작하는 줄과 빈 줄은 무시한다.

    Args:
        dict_path: 사용자 지정 사전 파일 경로.
                   None이면 기본 default_terms.txt + compound_terms.txt를 사용한다.

    Returns:
        도메인 용어 집합 (frozenset) — O(1) 멤버십 검사 보장.
        파일을 찾을 수 없거나 읽기에 실패하면 빈 frozenset 반환.
    """
    # 사용자 지정 경로가 있으면 해당 파일만 사용한다
    if dict_path is not None:
        return _read_terms_from_file(Path(dict_path))

    # 기본 사전과 복합어 사전을 합산하여 반환한다
    base_terms = _read_terms_from_file(_DEFAULT_DICT_PATH)
    compound_terms = _read_terms_from_file(_COMPOUND_DICT_PATH)
    return frozenset(base_terms | compound_terms)


def _read_terms_from_file(path: Path) -> frozenset[str]:
    """파일에서 용어를 읽어 frozenset으로 반환한다.

    파일이 존재하지 않거나 읽기 오류가 발생하면 빈 frozenset을 반환한다.
    각 줄의 앞뒤 공백을 제거하고, '#' 주석 줄과 빈 줄을 제외한다.

    Args:
        path: 읽어올 사전 파일의 절대 경로

    Returns:
        정제된 용어 집합 (frozenset[str])
    """
    if not path.exists():
        return frozenset()

    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        # 파일 읽기 실패 — 빈 집합으로 안전하게 처리
        return frozenset()

    terms: list[str] = []
    for line in raw_lines:
        term = _parse_term_line(line)
        if term:
            terms.append(term)

    return frozenset(terms)


def _parse_term_line(line: str) -> str:
    """한 줄에서 유효한 용어를 추출한다.

    주석('#' 시작) 또는 빈 줄이면 빈 문자열을 반환한다.

    Args:
        line: 사전 파일의 단일 텍스트 줄

    Returns:
        유효 용어 문자열, 해당 줄이 무효하면 빈 문자열
    """
    stripped = line.strip()
    # 빈 줄 또는 주석 줄 제외
    if not stripped or stripped.startswith("#"):
        return ""
    return stripped
