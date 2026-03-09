<p align="center">
  <img src="AppICON/icon_source_rgba.png" alt="OCR Module Icon" width="128" />
</p>

<h1 align="center">Mac Local AI-OCR</h1>
<p align="center">
  <b>GLM-OCR + 3-Model Ensemble for Apple Silicon</b><br/>
  100% 로컬 오프라인 AI 기반 PDF OCR 변환기
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-macOS%2014.0+-black?style=flat-square&logo=apple" alt="macOS" />
  <img src="https://img.shields.io/badge/Chip-Apple%20Silicon-blue?style=flat-square" alt="Apple Silicon" />
  <img src="https://img.shields.io/badge/License-AGPL--3.0-green?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/Pipeline-3Phase%20Sequential-orange?style=flat-square" alt="3-Phase Pipeline" />
</p>

---

이 프로젝트는 Apple Silicon Mac 환경에서 **100% 로컬 오프라인**으로 동작하는 AI 기반 PDF OCR(광학 문자 인식) 변환기입니다.
복잡한 전공 서적, 수식, 다이어그램, 코드가 포함된 문서를 GLM-OCR 모델로 텍스트를 추출하고, **3개 LLM 앙상블 후처리**로 교정하여 **'완벽하게 검색 및 복사가 가능한 PDF'**로 변환합니다.

## 3단계 순차 파이프라인

```
Phase 1: 병렬 OCR         Phase 2: 앙상블 후처리         Phase 3: PDF 생성
┌──────────────┐      ┌─────────────────────────┐     ┌──────────────┐
│  GLM-OCR     │      │ Qwen3 (한국어/영어)       │     │ 교정 텍스트   │
│  (torch MPS) │ ───→ │ EXAONE (고유명사/문맥)    │ ──→ │ + 원본 이미지 │
│  병렬 워커    │      │ DeepSeek-R1 (수학/코드)   │     │ → 최종 PDF   │
└──────────────┘      │       ↓ 다수결 투표        │     └──────────────┘
                      └─────────────────────────┘
```

> Phase 1에서 병렬 워커가 GLM-OCR로 텍스트를 추출하고, Phase 2에서 3개 LLM이 독립적으로 교정한 뒤 투표로 최종 결과를 결정합니다.

## 주요 기능

* **100% 로컬 구동:** 서버 전송 없이 Mac 내부 자원만 사용하여 개인정보 및 보안 문서 유출 위험 제로.
* **Apple Silicon 최적화:** OCR은 `torch MPS`(Metal GPU), 후처리는 `mlx-lm`으로 Apple Silicon을 100% 활용.
* **GLM-OCR 비전 모델:** 단순 글자 추출을 넘어, 다단 편집, 코드 블록, 표(Table) 구조를 이해하는 비전 모델 적용.
* **3-Model 앙상블 후처리:** Qwen3(한국어/영어) + EXAONE(고유명사/문맥) + DeepSeek-R1(수학/코드/표) 독립 교정 후 다수결 투표.
* **병렬 OCR 처리:** 복수 워커 프로세스가 PDF를 나누어 동시에 OCR 처리, 속도를 대폭 향상.
* **순차 메모리 관리:** 각 모델을 로드 → 처리 → 언로드 방식으로 동시 메모리 점유를 방지 (20GB 예산).
* **Tesseract 텍스트 위치 감지:** OCR 텍스트를 원본 위치에 정밀하게 오버레이.
* **도메인 사전 보정:** 글자 혼동 맵(CONFUSION_MAP) + 자모 다중 문자 보정 + 도메인 사전 대조.
* **콘텐츠 타입 분류:** 한국어/영어/수학/코드/표/혼합 자동 분류 → 전문가 모델 우선 반영.
* **직관적인 macOS 데스크탑 UI:** Flutter로 제작된 깔끔한 네이티브 앱 환경 제공.
* **청크 기반 처리:** 10페이지 단위 청크 처리로 1,000페이지 이상 대용량 문서도 안정 처리.
* **PDF 분할:** OCR 변환된 PDF를 원하는 N권으로 10페이지 단위 정렬 분할 저장.

## 기술 스택

| 레이어 | 기술 | 설명 |
| :--- | :--- | :--- |
| **Frontend** | Flutter (macOS Desktop) | 네이티브 macOS 데스크탑 앱 |
| **Backend** | Python (Virtual Env) | 파이프라인 컨트롤러 + OCR 엔진 |
| **OCR 모델** | GLM-OCR bf16 (zai-org) | transformers + torch MPS 비전 모델 |
| **후처리 모델 1** | Qwen3-8B-4bit (mlx) | 한국어/영어 텍스트 교정 |
| **후처리 모델 2** | EXAONE-7.8B-4bit (mlx) | 고유명사/문맥 검증 |
| **후처리 모델 3** | DeepSeek-R1-8B-4bit (mlx) | 수학/코드/표 구조 검증 |
| **텍스트 위치** | Tesseract (pytesseract) | OCR 텍스트 좌표 감지 |
| **PDF 처리** | PyMuPDF (fitz) | PDF 이미지 추출 + 병합 |
| **PDF 생성** | reportlab | 검색 가능 PDF 렌더링 |
| **병렬 처리** | multiprocessing (spawn) | 워커 프로세스 관리 |
| **통신 방식** | Subprocess (NDJSON stdout / JSON stderr) | Flutter ↔ Python 통신 |

## 시스템 요구 사항

> **3단계 순차 파이프라인으로 동시 메모리 점유를 최소화합니다. 피크 메모리는 단일 모델 최대 ~8GB입니다.**

| 항목 | 최소 사양 | 권장 사양 |
| :--- | :--- | :--- |
| **OS** | macOS 14.0 (Sonoma) | macOS 15.0+ |
| **Chip** | Apple Silicon (M1) | M3/M4 Pro 이상 |
| **RAM (통합 메모리)** | **16GB** | **24GB 이상** |
| **여유 메모리** | **10GB 이상** | 15GB+ |
| **디스크** | 20GB 여유 | 30GB+ (4개 모델 합산 ~15GB + 앱 + 임시 파일) |
| **Python** | 3.10 | 3.12+ |
| **Flutter** | 3.x | 3.38+ |

### 메모리 사용량 (순차 실행)

| 단계 | 로드 모델 | 피크 메모리 |
| :--- | :--- | :--- |
| Phase 1: OCR | GLM-OCR bf16 (워커당) | ~8GB |
| Phase 2-1: 후처리 | Qwen3-8B-4bit | ~6.5GB |
| Phase 2-2: 후처리 | EXAONE-7.8B-4bit | ~6.5GB |
| Phase 2-3: 후처리 | DeepSeek-R1-8B-4bit | ~6.5GB |
| Phase 3: PDF 생성 | (모델 불필요) | ~500MB |

> 각 모델은 순차적으로 로드/처리/언로드되므로 동시에 메모리를 점유하지 않습니다.

## 설치 및 실행 방법

터미널을 열고 아래 과정을 순서대로 진행해 주세요.

**1. 시스템 의존성 설치**

```bash
brew install flutter python@3.12 tesseract
```

**2. 프로젝트 클론 및 설치**

```bash
git clone https://github.com/algocean1204/Mac_OCR_APP.git
cd Mac_OCR_APP
./install.sh
```

**3. 앱 실행**

```bash
cd frontend
flutter run -d macos
```

> 최초 실행 시 HuggingFace에서 4개 모델(GLM-OCR + Qwen3 + EXAONE + DeepSeek-R1, 합산 ~15GB)을 자동 다운로드합니다.
> 모델은 `backend/AImodels/` 폴더에 캐시되며, 이후 재다운로드 없이 즉시 로드됩니다.

## CLI 직접 실행 (선택)

Flutter UI 없이 백엔드를 직접 실행할 수도 있습니다.

```bash
cd Mac_OCR_APP
source backend/.venv/bin/activate

# 기본 실행 (앙상블 후처리 활성화)
python -m backend.main --input /path/to/document.pdf

# 워커 1개로 실행 (16GB Mac)
python -m backend.main --input /path/to/document.pdf --workers 1

# 후처리 모드 변경
python -m backend.main --input /path/to/document.pdf --post-mode korean     # 한국어 교정만
python -m backend.main --input /path/to/document.pdf --post-mode reasoning  # 추론 검증만

# 4권 분할 + 출력 폴더 지정
python -m backend.main --input /path/to/document.pdf --split 4 --output-dir ~/Desktop

# 전체 옵션
python -m backend.main --help
```

| 옵션 | 기본값 | 설명 |
| :--- | :--- | :--- |
| `--input` | (필수) | 변환할 PDF 파일 경로 |
| `--output-dir` | `~/Downloads` | 출력 PDF 저장 디렉토리 |
| `--workers` | 자동 | 병렬 OCR 워커 수 (RAM 기반 자동 계산) |
| `--chunk-size` | `10` | 청크당 페이지 수 |
| `--split` | `1` | 출력 PDF 분할 권 수 (1 = 분할 없음) |
| `--dpi` | `300` | PDF 이미지 변환 해상도 |
| `--post-mode` | `ensemble` | 후처리 모드 (ensemble/korean/proper_noun/reasoning) |

## 사용 방법

1. 앱이 열리면 **PDF 파일을 드래그 앤 드롭**하거나 "파일 선택" 버튼을 클릭합니다.
2. 분할이 필요하면 **"몇 권으로 나눌까요?"** 필드에 원하는 숫자를 입력합니다.
3. **"변환 시작"** 버튼을 클릭합니다.
4. 변환이 완료되면 `~/Downloads/` 폴더에 결과 PDF가 자동 저장됩니다.
5. **"폴더 열기"** 버튼으로 바로 확인할 수 있습니다.

## 프로젝트 구조

```
Mac_OCR_APP/
├── install.sh                  # 원클릭 설치 스크립트
├── backend/                    # Python OCR 엔진
│   ├── main.py                 # 엔트리포인트
│   ├── config/
│   │   ├── settings.py         # 설정 관리 (CLI + 환경변수 + 기본값)
│   │   └── model_registry.py   # 모델 레지스트리 (4개 모델 사양 관리)
│   ├── pipeline/
│   │   ├── controller.py       # 3단계 파이프라인 오케스트레이터
│   │   ├── chunk_worker.py     # OCR 워커 (GLM-OCR + 도메인 보정)
│   │   ├── merger.py           # 청크 PDF 병합
│   │   └── page_processor.py   # 단일 페이지 처리
│   ├── pdf/
│   │   ├── extractor.py        # PyMuPDF PDF → 이미지 추출
│   │   ├── generator.py        # 검색 가능 PDF 생성 (위치 기반 텍스트 배치)
│   │   ├── splitter.py         # PDF N권 분할 (10페이지 단위 정렬)
│   │   └── atoms/
│   │       ├── detect_text_blocks.py    # 텍스트 블록 감지
│   │       └── extract_line_positions.py # Tesseract 기반 텍스트 위치 추출
│   ├── ocr/
│   │   ├── engine.py           # GLM-OCR 추론 엔진 (transformers + torch MPS)
│   │   ├── post_processor.py   # 앙상블 후처리 오케스트레이터
│   │   ├── prompt.py           # OCR 프롬프트 관리
│   │   └── atoms/
│   │       ├── batch_ocr.py              # 배치 OCR 처리
│   │       ├── block_ocr.py              # 블록 단위 OCR
│   │       ├── classify_content.py       # 콘텐츠 타입 분류 (rule-based)
│   │       ├── ensemble_voter.py         # 3-model 앙상블 투표
│   │       ├── build_refine_prompt.py    # 모델별 교정 프롬프트 생성
│   │       ├── correct_confusable_chars.py    # 글자 혼동 맵 보정
│   │       ├── correct_multichar_confusions.py # 자모 다중 문자 보정
│   │       ├── detect_text_regions.py    # 텍스트 영역 감지
│   │       ├── lightweight_correction.py # 경량 보정
│   │       ├── merge_sentence_blocks.py  # 문장 블록 병합
│   │       └── domain_dictionary.py      # 도메인 사전 대조
│   ├── model/
│   │   ├── downloader.py       # HuggingFace 모델 다운로드
│   │   └── validator.py        # 모델 무결성 검증
│   ├── memory/
│   │   └── manager.py          # 메모리 모니터링 + GC
│   ├── errors/                 # 에러 코드 + 예외 + 핸들러
│   ├── progress/               # NDJSON 진행률 보고
│   ├── utils/                  # 파일 유틸리티
│   ├── data/
│   │   └── default_terms.txt   # 도메인 사전 (고유명사 등)
│   └── AImodels/               # 모델 캐시 (gitignore, 최초 실행 시 다운로드)
├── frontend/                   # Flutter macOS 앱
│   └── lib/
│       ├── screens/            # 메인 화면
│       ├── widgets/            # UI 컴포넌트
│       ├── services/           # Python subprocess 통신
│       └── models/             # 상태 모델
├── shared/types/               # 통신 프로토콜 스키마
├── docs/                       # 설계 문서
└── AppICON/                    # 앱 아이콘
```

## 동작 방식

```
Flutter UI ──> Python Subprocess 호출
                    │
          ═══ Phase 1: 병렬 OCR ═══
                    │
            [메인 프로세스]
                    ├── PDF 검증 + 페이지 수 확인
                    ├── 모델 다운로드 확인 (최초 1회)
                    ├── 페이지를 N등분하여 워커에 할당
                    │
              ┌─────┼─────┐
          [워커 0] [워커 1] ...        ← multiprocessing.Process (spawn)
              │       │
              ├─ GLM  ├─ GLM            ← transformers + torch MPS
              ├─ OCR  ├─ OCR
              ├─ 도메인보정 ├─ 도메인보정  ← CONFUSION_MAP + 사전
              ├─ JSON ├─ JSON           ← 텍스트 결과 저장
              └─────┼─────┘
                    │
          ═══ Phase 2: 앙상블 후처리 ═══
                    │
            [메인 프로세스]
                    ├── Qwen3 로드 → 전체 교정 → 언로드
                    ├── EXAONE 로드 → 전체 교정 → 언로드
                    ├── DeepSeek-R1 로드 → 전체 교정 → 언로드
                    ├── 콘텐츠 타입별 앙상블 투표 → 최종 텍스트
                    │
          ═══ Phase 3: PDF 생성 ═══
                    │
            [메인 프로세스]
                    ├── Tesseract로 원본 텍스트 위치 감지
                    ├── 교정 텍스트를 위치에 맞게 투명 배치
                    ├── 원본 이미지 + 텍스트 레이어 → PDF
                    ├── (선택) N권 분할 (10페이지 단위 정렬)
                    └── 임시 파일 정리
                    │
Flutter UI <── NDJSON stdout으로 진행률 실시간 전달
```

## 핵심 기술 특징

* **3단계 순차 파이프라인:** OCR → 앙상블 후처리 → PDF 생성을 분리하여 메모리 효율을 극대화.
* **GLM-OCR (transformers + torch MPS):** Apple Silicon Metal GPU를 직접 활용하는 비전 모델.
* **3-Model 앙상블 투표:** 만장일치 > 사전 검증 > 다수결(2/3) > 전문가(콘텐츠 타입별) 우선순위.
* **콘텐츠 타입 분류:** 한국어/영어/수학/코드/표/혼합을 자동 분류, 전문가 모델에 가중치 부여.
* **3계층 도메인 보정:** 글자 혼동 맵(char-level) → 자모 다중 문자 보정 → LLM 후처리.
* **순차 메모리 관리:** 각 모델을 로드→처리→언로드하여 동시 점유 방지 (피크 ~8GB).
* **Tesseract 위치 감지:** PSM 6(단일 블록) → PSM 11(희소) 폴백으로 텍스트 좌표 추출.
* **청크 기반 처리:** 10페이지 단위로 처리하여 1,000페이지 이상도 안정 처리.
* **실패 복구:** 개별 페이지 OCR 실패 시 이미지만 추가하고 나머지 계속 처리.
* **CJK 폰트 지원:** 한국어/중국어/일본어 텍스트를 투명 레이어에 정확하게 매핑.
* **macOS spawn 호환:** Apple Silicon Metal/MPS와 호환되는 `multiprocessing.spawn` 사용.

## 라이선스 (License & Copyright)

### GNU AGPL-3.0 License

이 프로젝트는 **누구나 평생 무료로 사용할 수 있는 오픈소스 생태계**를 지향하며, 상업적 기업의 무단 소스코드 도용 및 클로즈드 소스화를 막기 위해 **AGPL-3.0** 라이선스를 채택했습니다. (내부적으로 사용하는 PyMuPDF의 라이선스 정책을 준수합니다.)

* **개인 사용자:** 자유롭게 다운로드하고 변형하여 무료로 사용할 수 있습니다.
* **개발자 및 기업:** 이 프로젝트의 코드를 사용하여 만든 파생 프로그램이나, 이를 백엔드로 활용한 웹/클라우드 서비스(SaaS)를 대중에게 제공할 경우, 반드시 그 서비스의 **전체 소스코드도 대중에게 동일한 AGPL-3.0 라이선스로 공개**해야 합니다. 코드를 닫아둔 채로 이익만 취하는 행위는 엄격히 금지됩니다.
