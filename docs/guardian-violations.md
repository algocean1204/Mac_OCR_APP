# Guardian Violation Report

## 모니터링 시작 시각: Implementation Phase 시작 시점
## 모니터 대상: frontend/lib/, backend/ (연결 부분만), NDJSON 프로토콜

---

## [VIOLATION-001] Severity: P2
- **Discovery point**: 초기 모니터링, 파일 크기 점검
- **Violating agent**: (기존 코드)
- **Violation type**: 파일 크기 규칙 위반 (CLAUDE.md: 파일 200줄, 컴포넌트 150줄 제한)
- **Violation details**: 다수 파일이 200줄 / 300줄 제한을 초과함
  - backend/pipeline/controller.py: 812줄
  - backend/pdf/generator.py: 731줄
  - backend/pipeline/chunk_worker.py: 497줄
  - frontend/lib/widgets/progress_view.dart: 475줄 (컴포넌트 150줄 제한 초과)
  - frontend/lib/screens/home_screen.dart: 402줄 (컴포넌트 150줄 제한 초과)
  - frontend/lib/widgets/file_selected_view.dart: 336줄 (컴포넌트 150줄 제한 초과)
  - frontend/lib/widgets/complete_view.dart: 273줄 (컴포넌트 150줄 제한 초과)
  - frontend/lib/models/ocr_state.dart: 264줄 (200줄 제한 초과)
  - frontend/lib/services/ocr_service.dart: 204줄 (200줄 제한 초과)
- **Correction order**: 현재 Phase에서 기능 수정이 우선. 신규 추가 위젯은 반드시 150줄 이내로 작성하고, 기존 대형 파일은 기능 추가 시 분할 기회 활용.
- **Status**: OPEN (기존 코드의 기술 부채, 신규 코드에서만 강제)

## [VIOLATION-002] Severity: P3
- **Discovery point**: 초기 모니터링, type: ignore 스캔
- **Violating agent**: (기존 코드)
- **Violation type**: 우회 코드 패턴 — type: ignore 다수 사용
- **Violation details**: 총 24건의 `# type: ignore` 사용
  - backend/errors/exceptions.py: 6건
  - backend/ocr/atoms/clean_latex.py: 6건
  - backend/pdf/atoms/extract_line_positions.py: 4건
  - backend/pdf/atoms/detect_text_blocks.py: 2건
  - backend/progress/reporter.py: 1건
  - 기타: 5건
- **Correction order**: 대부분 서드파티 라이브러리(pytesseract, fitz) 타입 정의 부재로 인한 것. WORKAROUND 주석 형식으로 전환이 이상적이나, 현 Phase에서는 신규 코드에서의 type: ignore 추가만 금지.
- **Status**: OPEN (기존 기술 부채)

## [VIOLATION-003] Severity: P3
- **Discovery point**: 초기 모니터링, 영어 주석 스캔
- **Violating agent**: (기존 코드)
- **Violation type**: 영어 단어 포함 주석
- **Violation details**: "Phase", "Python", "OCR" 등 기술 용어가 주석에 포함됨. 이들은 고유 기술 명칭이므로 번역이 부적절한 경우가 대부분이다.
- **Correction order**: 기술 용어(Phase, Python, OCR, JSON, NDJSON 등)는 한국어 대체어가 없으므로 허용. 순수 영어 설명 문장은 금지.
- **Status**: PASS (기술 용어 예외)

---

## [OCR 코어 수정 감시 — P0 검증 결과]

### 현재 git diff 기준 변경된 백엔드 파일 검증:

1. **backend/config/settings.py** — DPI 300→200, NUM_WORKERS 2→1
   - 판정: P1 주의. 설정값 변경은 OCR 추론 로직 자체가 아닌 성능 파라미터 조정이지만 품질에 영향을 줄 수 있다. 사용자 인지 필요.
   - Status: INFO — 사용자에게 보고 완료

2. **backend/ocr/atoms/build_refine_prompt.py** — 프롬프트 압축 + should_refine 임계값 변경
   - 판정: P1 주의. 프롬프트 내용 대폭 축소(300→80 토큰)는 후처리 품질에 영향 줄 수 있음.
   - Status: INFO — 사용자에게 보고 완료

3. **backend/ocr/post_processor.py** — max_tokens 4096→2048, 동적 토큰 추정, DeepSeek-R1 thinking 억제
   - 판정: P1 주의. 후처리 파라미터 변경은 OCR 추론 자체는 아니지만 최종 품질에 영향.
   - Status: INFO — 사용자에게 보고 완료

4. **backend/pipeline/chunk_worker.py** — 블록 파이프라인 조건화(quick_table_check) + Tesseract 캐시 추가
   - 판정: P1 주의. OCR 추론 로직 자체는 변경 안 했으나, 블록 파이프라인 호출 조건이 변경됨. Tesseract 캐시 추가는 Phase 3 성능 개선으로 적합.
   - Status: INFO — 사용자에게 보고 완료

5. **backend/pipeline/controller.py** — 후처리 진행률 보고, DeepSeek-R1 선택적 스킵, Tesseract 캐시 전달
   - 판정: 진행률 보고 추가는 프론트엔드 연결 개선으로 적합. DeepSeek-R1 스킵은 최적화지만 앙상블 결과에 영향.
   - Status: INFO — 사용자에게 보고 완료

6. **backend/pdf/generator.py** — add_page_with_cached_positions 메서드 추가
   - 판정: PASS. 새 메서드 추가이며 기존 메서드는 변경 안 됨.
   - Status: PASS

### 프론트엔드 변경 검증:

7. **frontend/lib/screens/home_screen.dart** — originalTotalPages 추가, Phase 변경 감지 로직
   - 판정: PASS. 프론트엔드 상태 관리 개선.

8. **frontend/lib/screens/home_screen_builder.dart** — originalTotalPages 파라미터 전달
   - 판정: PASS. 파라미터 전달 추가.

9. **frontend/lib/screens/home_state_handler.dart** — post_processing, generating_pdf 상태 번역 추가
   - 판정: PASS. 백엔드 status 매핑 추가.

10. **frontend/lib/widgets/progress_view.dart** — Phase 별 헤더 표시, 모델별 진행률 계산
    - 판정: PASS. UI 개선.

---

## 프로토콜 정합성 검증 결과

### 백엔드 reporter.py 이벤트 타입 ↔ 프론트엔드 OcrEvent.fromJson 매핑:

| Backend type | Frontend OcrEventType | 매핑 상태 |
|---|---|---|
| init | OcrEventType.init | PASS |
| progress | OcrEventType.progress | PASS |
| download | OcrEventType.download | PASS |
| complete | OcrEventType.complete | PASS |
| split_progress | OcrEventType.splitProgress | PASS |
| split_complete | OcrEventType.splitComplete | PASS |
| log | OcrEventType.log | PASS |
| page_error (stderr) | OcrEventType.error (recoverable) | PASS |

### 누락된 데이터 연결:

1. **page_error에서 페이지 번호 미전달** — P0 태스크
   - 백엔드 chunk_worker.py의 page_error 메시지에 page_num이 포함되지만, ocr_state.dart의 page_error 파서가 page_num을 캡처하지 않는다.
   - 프론트엔드에서는 어떤 페이지가 실패했는지 표시 불가.
   - **구현 필요**

2. **log 이벤트 미활용** — P1 태스크
   - home_screen.dart의 case OcrEventType.log: 에서 단순 break 처리.
   - 앙상블 투표 통계, 콘텐츠 분류 결과 등 유용한 정보가 log로 전송되지만 UI에 표시 안 됨.
   - **구현 필요**

3. **후처리 진행률 memory_mb 정상 작동 확인** — controller.py 수정으로 해결
   - controller.py의 _run_sequential_post_processing에서 memory_mb=int(get_memory_mb()) 추가됨.
   - **RESOLVED**

---

## 현재 Phase 완료 전 체크리스트

- [ ] P0: page_error에서 실패 페이지 번호 캡처 및 표시
- [ ] P1: log 이벤트를 확장 패널에 표시
- [ ] P1: 앙상블 투표 통계 표시
- [ ] P1: 콘텐츠 분류 결과 표시
- [ ] P1: 메모리 경고 배너
- [ ] P2: Phase 2에서 모델 이름 표시
- [ ] P2: macOS 네이티브 알림
- [ ] P2: 디자인/애니메이션 개선
- [ ] P2: 실시간 진행상황 추가 강화
- [ ] 신규 코드: 한국어 주석 100%
- [ ] 신규 코드: 파일/컴포넌트 크기 제한 준수
- [ ] 신규 코드: type: ignore / workaround 패턴 없음
- [ ] OCR 코어 파일 미변경 확인
- [ ] NDJSON 프로토콜 호환성 유지
