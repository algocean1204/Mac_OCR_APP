// OCR 처리 진행률 데이터 모델
// progress 이벤트와 download 이벤트 수신 시 UI에 표시되는 데이터이다.
// PDF 분할 진행률(SplitProgress) 모델도 포함한다.

/// 로그 메시지 엔트리 — 백엔드에서 수신한 로그를 저장한다
class LogEntry {
  /// 로그 레벨 (debug / info / warn)
  final String level;

  /// 로그 메시지 본문
  final String message;

  /// 로그 수신 시각
  final DateTime timestamp;

  const LogEntry({
    required this.level,
    required this.message,
    required this.timestamp,
  });
}

/// 개별 워커의 진행률 데이터
class WorkerProgress {
  /// 워커 ID (0-based)
  final int workerId;

  /// 해당 워커가 완료한 페이지 수
  final int completed;

  /// 해당 워커에 할당된 총 페이지 수
  final int total;

  const WorkerProgress({
    required this.workerId,
    required this.completed,
    required this.total,
  });

  /// 진행률 (0.0 ~ 1.0)
  double get progress => total > 0 ? (completed / total).clamp(0.0, 1.0) : 0.0;
}

/// 처리 중 진행률 데이터를 담는 데이터 클래스
class ProcessingProgress {
  /// 현재 처리 중인 페이지 번호 (1-based)
  final int currentPage;

  /// 전체 페이지 수
  final int totalPages;

  /// 완료 퍼센트 (0.0 ~ 100.0)
  final double percent;

  /// 현재 처리 상태 설명
  final String statusText;

  /// 현재 메모리 사용량 (MB)
  final double memoryMb;

  /// 처리 시작 시각
  final DateTime startTime;

  /// 스킵된 페이지 수
  final int skippedPages;

  /// 실패한 페이지 번호 목록 (page_error 이벤트에서 수집한다)
  final List<int> failedPages;

  /// 총 워커 수 (병렬 처리 워커 개수)
  final int numWorkers;

  /// 워커별 진행 정보 목록
  final List<WorkerProgress> workerProgress;

  /// 실제 OCR 처리 시작 시각 (첫 page_done 시점)
  /// 모델 로딩 시간을 제외한 순수 처리 시간 계산에 사용한다.
  final DateTime? ocrStartTime;

  const ProcessingProgress({
    required this.currentPage,
    required this.totalPages,
    required this.percent,
    required this.statusText,
    required this.memoryMb,
    required this.startTime,
    required this.skippedPages,
    this.failedPages = const [],
    this.numWorkers = 0,
    this.workerProgress = const [],
    this.ocrStartTime,
  });

  /// 경과 시간 (초)
  double get elapsedSeconds =>
      DateTime.now().difference(startTime).inMilliseconds / 1000.0;

  /// 페이지당 평균 처리 시간 (초)
  /// 모델 로딩 시간을 제외하기 위해 ocrStartTime 기준으로 계산한다.
  double get secondsPerPage {
    if (currentPage <= 0 || ocrStartTime == null) return 0;
    final ocrElapsed =
        DateTime.now().difference(ocrStartTime!).inMilliseconds / 1000.0;
    return ocrElapsed / currentPage;
  }

  /// 예상 잔여 시간 (초)
  double get estimatedRemainingSeconds {
    final remaining = totalPages - currentPage;
    if (remaining <= 0 || secondsPerPage <= 0) return 0;
    return remaining * secondsPerPage;
  }

  ProcessingProgress copyWith({
    int? currentPage,
    int? totalPages,
    double? percent,
    String? statusText,
    double? memoryMb,
    DateTime? startTime,
    int? skippedPages,
    List<int>? failedPages,
    int? numWorkers,
    List<WorkerProgress>? workerProgress,
    DateTime? ocrStartTime,
  }) {
    return ProcessingProgress(
      currentPage: currentPage ?? this.currentPage,
      totalPages: totalPages ?? this.totalPages,
      percent: percent ?? this.percent,
      statusText: statusText ?? this.statusText,
      memoryMb: memoryMb ?? this.memoryMb,
      startTime: startTime ?? this.startTime,
      skippedPages: skippedPages ?? this.skippedPages,
      failedPages: failedPages ?? this.failedPages,
      numWorkers: numWorkers ?? this.numWorkers,
      workerProgress: workerProgress ?? this.workerProgress,
      ocrStartTime: ocrStartTime ?? this.ocrStartTime,
    );
  }
}

/// PDF 분할 진행률 데이터를 담는 데이터 클래스
class SplitProgress {
  /// 현재 처리 중인 분할 권 번호 (1-based)
  final int currentPart;

  /// 전체 분할 권 수
  final int totalParts;

  /// 이 권의 시작 페이지
  final int startPage;

  /// 이 권의 끝 페이지
  final int endPage;

  const SplitProgress({
    required this.currentPart,
    required this.totalParts,
    required this.startPage,
    required this.endPage,
  });
}

/// 다운로드 진행률 데이터를 담는 데이터 클래스
class DownloadProgress {
  /// 다운로드된 용량 (MB)
  final double downloadedMb;

  /// 전체 다운로드 크기 (MB)
  final double totalMb;

  /// 완료 퍼센트 (0.0 ~ 100.0)
  final double percent;

  /// 다운로드 상태 텍스트
  final String statusText;

  const DownloadProgress({
    required this.downloadedMb,
    required this.totalMb,
    required this.percent,
    required this.statusText,
  });
}
