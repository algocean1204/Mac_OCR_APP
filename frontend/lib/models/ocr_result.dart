// OCR 처리 완료 결과 데이터 모델
// complete 이벤트 수신 후 UI에서 결과를 표시할 때 사용한다.
// 분할 기능 추가: splitParts, totalParts 필드 포함.

/// OCR 처리 완료 결과 데이터 클래스
class OcrResult {
  /// 출력 파일 경로 (분할 없을 때 단일 파일)
  final String outputPath;

  /// 처리된 총 페이지 수
  final int totalPages;

  /// 스킵된 페이지 수
  final int skippedPages;

  /// 총 소요 시간 (초)
  final double elapsedSeconds;

  /// 분할된 파일 경로 목록 (분할하지 않으면 빈 리스트)
  final List<String> splitParts;

  /// 분할 권 수 (분할 없으면 1)
  final int totalParts;

  const OcrResult({
    required this.outputPath,
    required this.totalPages,
    required this.skippedPages,
    required this.elapsedSeconds,
    this.splitParts = const [],
    this.totalParts = 1,
  });

  /// 분할 작업이 수행되었는지 여부
  bool get isSplit => totalParts > 1 && splitParts.isNotEmpty;

  /// 소요 시간을 읽기 쉬운 형태로 포맷한다.
  String get formattedElapsedTime {
    final mins = (elapsedSeconds / 60).floor();
    final secs = (elapsedSeconds % 60).floor();
    if (mins > 0) {
      return '$mins분 $secs초';
    }
    return '$secs초';
  }
}
