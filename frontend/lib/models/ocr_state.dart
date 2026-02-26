// OCR 상태 머신 및 이벤트 모델 정의
// 앱의 현재 상태와 Python 백엔드로부터 수신하는 이벤트 타입을 정의한다.

// 진행률/결과 모델은 별도 파일로 분리됨
export 'ocr_progress.dart';
export 'ocr_result.dart';

/// OCR 앱의 전체 상태를 나타내는 열거형
enum OcrAppState {
  /// 초기 상태 -- 파일 선택 대기 중
  idle,

  /// 파일 선택 완료 -- 변환 시작 버튼 활성화 상태
  fileSelected,

  /// AI 모델 다운로드 중 (최초 실행 시)
  downloadingModel,

  /// OCR 처리 중
  processing,

  /// 처리 완료
  complete,

  /// 에러 발생
  error,
}

/// Python 백엔드로부터 수신하는 이벤트 타입
enum OcrEventType {
  /// 초기화 완료 (모델 로드 완료, 페이지 수 확인 완료)
  init,

  /// 모델 다운로드 진행률
  download,

  /// 페이지 처리 진행률
  progress,

  /// 전체 처리 완료
  complete,

  /// 에러 발생
  error,

  /// 로그 메시지 (디버깅용)
  log,

  /// PDF 분할 진행률 (OCR 완료 후 분할 작업 중)
  splitProgress,

  /// PDF 분할 완료
  splitComplete,

  /// 모델 초기 설정 중 (다운로드/로드 관련 서드파티 출력 감지)
  modelSetup,
}

/// OCR 이벤트 데이터 클래스 -- Python stdout/stderr로부터 파싱된 메시지
class OcrEvent {
  final OcrEventType type;

  // init 이벤트 필드
  final String? modelName;
  final bool? modelLoaded;

  // progress / init 공통 필드
  final int? totalPages;

  // progress 이벤트 필드
  final int? currentPage;
  final double? percent;
  final String? status;
  final double? memoryMb;

  // progress 이벤트 워커 관련 필드
  final int? numWorkers;
  final List<Map<String, dynamic>>? workerProgressData;

  // download 이벤트 필드
  final double? downloadedMb;
  final double? totalMb;

  // complete 이벤트 필드
  final String? outputPath;
  final double? elapsedSeconds;

  // error 이벤트 필드
  final String? errorCode;
  final String? errorMessage;
  final bool? recoverable;

  // log 이벤트 필드
  final String? logLevel;
  final String? logMessage;

  // split_progress 이벤트 필드
  final int? currentPart;
  final int? totalParts;
  final int? startPage;
  final int? endPage;

  // split_complete 이벤트 필드
  final List<String>? splitPartPaths;

  // 공통 필드
  final String? timestamp;

  const OcrEvent({
    required this.type,
    this.modelName,
    this.modelLoaded,
    this.totalPages,
    this.currentPage,
    this.percent,
    this.status,
    this.memoryMb,
    this.numWorkers,
    this.workerProgressData,
    this.downloadedMb,
    this.totalMb,
    this.outputPath,
    this.elapsedSeconds,
    this.errorCode,
    this.errorMessage,
    this.recoverable,
    this.logLevel,
    this.logMessage,
    this.currentPart,
    this.totalParts,
    this.startPage,
    this.endPage,
    this.splitPartPaths,
    this.timestamp,
  });

  /// JSON Map으로부터 OcrEvent를 생성한다.
  /// 알 수 없는 타입이면 null을 반환한다.
  static OcrEvent? fromJson(Map<String, dynamic> json) {
    final typeStr = json['type'] as String?;
    if (typeStr == null) return null;

    switch (typeStr) {
      case 'init':
        return OcrEvent(
          type: OcrEventType.init,
          modelName: json['model_name'] as String?,
          modelLoaded: json['model_loaded'] as bool?,
          totalPages: json['total_pages'] as int?,
          timestamp: json['timestamp'] as String?,
        );

      case 'download':
        return OcrEvent(
          type: OcrEventType.download,
          downloadedMb: (json['downloaded_mb'] as num?)?.toDouble(),
          totalMb: (json['total_mb'] as num?)?.toDouble(),
          percent: (json['percent'] as num?)?.toDouble(),
          status: json['status'] as String?,
          timestamp: json['timestamp'] as String?,
        );

      case 'progress':
        return OcrEvent(
          type: OcrEventType.progress,
          currentPage: json['current_page'] as int?,
          totalPages: json['total_pages'] as int?,
          percent: (json['percent'] as num?)?.toDouble(),
          status: json['status'] as String?,
          memoryMb: (json['memory_mb'] as num?)?.toDouble(),
          numWorkers: json['num_workers'] as int?,
          // worker_progress 배열을 Map 리스트로 변환하여 저장한다
          workerProgressData: (json['worker_progress'] as List<dynamic>?)
              ?.map((e) => Map<String, dynamic>.from(e as Map))
              .toList(),
          timestamp: json['timestamp'] as String?,
        );

      case 'complete':
        return OcrEvent(
          type: OcrEventType.complete,
          outputPath: json['output_path'] as String?,
          totalPages: json['total_pages'] as int?,
          elapsedSeconds: (json['elapsed_seconds'] as num?)?.toDouble(),
          timestamp: json['timestamp'] as String?,
        );

      case 'error':
        return OcrEvent(
          type: OcrEventType.error,
          errorCode: json['code'] as String?,
          errorMessage: json['message'] as String?,
          recoverable: json['recoverable'] as bool?,
          timestamp: json['timestamp'] as String?,
        );

      // page_error -- 개별 페이지 처리 실패 (Python stderr에서 수신)
      // 복구 가능한 에러로 처리하여 스킵 카운터를 증가시킨다.
      case 'page_error':
        return OcrEvent(
          type: OcrEventType.error,
          errorCode: json['code'] as String?,
          errorMessage: json['message'] as String?,
          recoverable: true,
          timestamp: json['timestamp'] as String?,
        );

      case 'log':
        return OcrEvent(
          type: OcrEventType.log,
          logLevel: json['level'] as String?,
          logMessage: json['message'] as String?,
          timestamp: json['timestamp'] as String?,
        );

      // PDF 분할 진행률 이벤트
      case 'split_progress':
        return OcrEvent(
          type: OcrEventType.splitProgress,
          currentPart: json['current_part'] as int?,
          totalParts: json['total_parts'] as int?,
          startPage: json['start_page'] as int?,
          endPage: json['end_page'] as int?,
          timestamp: json['timestamp'] as String?,
        );

      // PDF 분할 완료 이벤트
      case 'split_complete':
        final rawParts = json['parts'];
        final List<String> parsedParts = rawParts is List
            ? rawParts.map((e) => e.toString()).toList()
            : [];
        return OcrEvent(
          type: OcrEventType.splitComplete,
          splitPartPaths: parsedParts,
          totalParts: json['total_parts'] as int?,
          timestamp: json['timestamp'] as String?,
        );

      default:
        return null;
    }
  }

  /// 에러 이벤트를 직접 생성하는 팩토리 메서드
  factory OcrEvent.fromError(String message) {
    return OcrEvent(
      type: OcrEventType.error,
      errorCode: 'E999',
      errorMessage: message,
      recoverable: false,
    );
  }

  /// 모델 초기 설정 이벤트를 생성하는 팩토리 메서드
  /// 서드파티 라이브러리의 다운로드/로드 관련 stderr 출력을 감지했을 때 사용한다.
  factory OcrEvent.modelSetup(String rawLine) {
    return OcrEvent(
      type: OcrEventType.modelSetup,
      logLevel: 'info',
      logMessage: rawLine,
    );
  }
}
