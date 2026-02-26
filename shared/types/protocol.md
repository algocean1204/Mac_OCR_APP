# OCR 모듈 통신 프로토콜 명세

> 작성일: 2026-02-25
> 대상: Flutter 프론트엔드 ↔ Python 백엔드
> 방식: Subprocess stdout/stderr NDJSON

---

## 통신 방식 요약

| 방향 | 채널 | 형식 | 용도 |
|---|---|---|---|
| Python → Flutter | stdout | NDJSON (한 줄 = 한 JSON) | 진행률, 완료, 로그 |
| Python → Flutter | stderr | JSON | 에러 메시지만 |
| Flutter → Python | stdin | 텍스트 | 취소 명령만 |
| Flutter → Python | CLI 인자 | `--input`, `--output-dir` | 초기 설정 |

---

## stdout 메시지 타입

### init — 초기화 완료
```json
{
  "type": "init",
  "model_name": "mlx-community/DeepSeek-OCR-2-8bit",
  "model_loaded": true,
  "total_pages": 142,
  "timestamp": "2026-02-25T10:30:00"
}
```

### progress — 페이지 처리 진행률
```json
{
  "type": "progress",
  "current_page": 15,
  "total_pages": 142,
  "percent": 10.56,
  "status": "ocr_processing",
  "memory_mb": 3842,
  "timestamp": "2026-02-25T10:30:15"
}
```

`status` 값:
- `extracting_image`: PDF에서 이미지 추출 중
- `ocr_processing`: MLX 모델 OCR 추론 중
- `writing_output`: 출력 PDF에 텍스트 기록 중
- `page_complete`: 페이지 처리 완료 + 메모리 해제 완료

### download — 모델 다운로드 진행률
```json
{
  "type": "download",
  "downloaded_mb": 2048,
  "total_mb": 4500,
  "percent": 45.5,
  "status": "downloading",
  "timestamp": "2026-02-25T10:28:00"
}
```

### complete — 처리 완료
```json
{
  "type": "complete",
  "output_path": "~/Downloads/document_OCR.pdf",
  "total_pages": 142,
  "elapsed_seconds": 854.3,
  "timestamp": "2026-02-25T10:44:14"
}
```

### log — 디버깅 로그
```json
{
  "type": "log",
  "level": "info",
  "message": "모델 캐시 확인 완료",
  "timestamp": "2026-02-25T10:29:55"
}
```

---

## stderr 메시지 타입

### error — 치명적 에러
```json
{
  "type": "error",
  "code": "E001",
  "message": "PDF 파일을 열 수 없음",
  "details": "fitz.FileDataError: cannot open broken document",
  "recoverable": false,
  "timestamp": "2026-02-25T10:30:01"
}
```

### page_error — 페이지 처리 실패 (건너뜀)
```json
{
  "type": "page_error",
  "page": 15,
  "code": "E020",
  "message": "페이지 OCR 실패 — 해당 페이지를 건너뜀",
  "details": "TimeoutError",
  "recoverable": true,
  "timestamp": "2026-02-25T10:32:15"
}
```

---

## 에러 코드 체계

| 코드 | 카테고리 | 복구 가능 |
|---|---|---|
| E001 | PDF 열기 실패 | X |
| E002 | PDF 없음 | X |
| E003 | PDF 콘텐츠 없음 | X |
| E010 | 모델 다운로드 실패 | O (재시도) |
| E011 | 모델 파일 손상 | O (재다운로드) |
| E012 | 모델 로드 실패 | X |
| E013 | MLX 호환 불가 | X |
| E020 | 페이지 OCR 실패 | O (건너뛰기) |
| E021 | OCR 타임아웃 | O (건너뛰기) |
| E030 | 출력 PDF 생성 실패 | X |
| E031 | 디스크 공간 부족 | X |
| E040 | 메모리 경고 | O (GC 강제) |
| E041 | 메모리 치명 | X |
| E050 | 패키지 미설치 | X |
| E051 | 미지원 플랫폼 | X |

---

## stdin 취소 명령

Flutter에서 Python에 취소를 요청할 때는 stdin에 다음을 보낸다:

```
CANCEL\n
```

Python은 현재 페이지 처리를 완료한 후 안전하게 종료한다.
처리된 페이지까지의 부분 결과는 저장된다.

---

## 프로세스 종료 코드

| 코드 | 의미 |
|---|---|
| 0 | 정상 종료 (완료 또는 취소) |
| 1 | 에러 종료 |
