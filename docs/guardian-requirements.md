# Guardian Requirements Log

## 사용자 원본 요구사항
1. 백앤드(DB)랑 프론트앤드 위치 연결 전부 조사하고 잘못된 부분 수정
2. 디자인, 사용자 편의등 추가할 프론트앤드 요소들 추가
3. 실제 진행상황, 실시간 진행상황등 추가할것들 추가
4. OCR 코어 기능은 건들지 않음 — 프론트엔드 위주 수정
5. Requirements guardian 병렬 실행 필수
6. 서브 에이전트 순차 할당

## Current Phase: Implementation (P0→P1→P2 순차 구현)
## Phase Goal: 프론트엔드-백엔드 연결 정합성 검증 + 프론트엔드 기능 추가 + 실시간 진행상황 개선
## Active Agents: general-purpose sub-agents (순차 할당)

## Critical Requirements (즉시 개입)
- [CRITICAL] OCR 핵심 기능 절대 수정 금지 (backend/ocr/engine.py, backend/ocr/atoms/ 추론 로직, ensemble_voter.py, chunk_worker.py OCR 추론 로직)
- [CRITICAL] 프론트엔드 위주 수정 — 백엔드는 progress reporting 등 프론트 연결 부분만 최소 수정
- [CRITICAL] 범용적 설계 — 특정 PDF에 종속되지 않게
- [CRITICAL] NDJSON 프로토콜 호환성 유지

## Standard Requirements (Phase 완료 전 검증)
- 프론트엔드 데이터 모델이 백엔드 NDJSON 프로토콜과 완전히 일치하는지 검증
- 모든 상태 전환이 올바르게 처리되는지 확인
- 한국어 주석, 타입 힌트, 원자 모듈 패턴 준수
- 우회 코드(workaround) 금지
- 파일 크기 제한 준수 (파일 200줄, 컴포넌트 150줄)

## Implementation Task List
### P0 (Critical):
- [ ] Fix page_error page number capture in ocr_state.dart — 어떤 페이지가 실패했는지 표시
### P1 (High):
- [ ] Display log/debug messages in expandable panel
- [ ] Show ensemble voting statistics
- [ ] Show content type classification
- [ ] Memory warning banner
### P2 (Medium):
- [ ] Show model names during Phase 2
- [ ] macOS native notifications on completion
- [ ] Design improvements (animations, better layout)
- [ ] Real-time enhancements
