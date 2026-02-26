// 파일 시스템 관련 작업을 담당하는 서비스
// PDF 파일 유효성 검사, 출력 폴더 열기, 파일 경로 관리 등을 처리한다.

import 'dart:io';

/// 파일 서비스 -- 파일 시스템 작업 전담
class FileService {
  /// PDF 파일 경로가 유효한지 검사한다.
  /// .pdf 확장자 확인 및 파일 존재 여부를 확인한다.
  bool isValidPdfPath(String path) {
    // 확장자가 .pdf인지 확인 (대소문자 무관)
    if (!path.toLowerCase().endsWith('.pdf')) {
      return false;
    }
    // 파일이 실제로 존재하는지 확인
    return File(path).existsSync();
  }

  /// 파일 경로에서 파일명만 추출한다. (경로 구분자 처리)
  String getFileName(String path) {
    return path.split('/').last;
  }

  /// 파일 크기를 사람이 읽기 쉬운 형태로 반환한다. (예: "3.2 MB")
  String getFileSizeString(String path) {
    try {
      final file = File(path);
      if (!file.existsSync()) return '알 수 없음';
      final bytes = file.lengthSync();
      return _formatBytes(bytes);
    } catch (_) {
      return '알 수 없음';
    }
  }

  /// 바이트 수를 읽기 쉬운 문자열로 변환한다.
  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }

  /// macOS Finder에서 특정 파일 또는 폴더를 연다.
  /// 파일 경로를 지정하면 해당 파일이 선택된 상태로 Finder가 열린다.
  Future<void> revealInFinder(String path) async {
    try {
      // macOS의 open 명령을 사용하여 Finder에서 파일 위치 표시
      await Process.run('open', ['-R', path]);
    } catch (e) {
      // open 명령 실패 시 상위 디렉토리라도 열기
      final dir = File(path).parent.path;
      await Process.run('open', [dir]);
    }
  }

  /// macOS Finder에서 폴더를 연다.
  Future<void> openFolder(String folderPath) async {
    try {
      await Process.run('open', [folderPath]);
    } catch (_) {
      // 폴더 열기 실패 시 무시
    }
  }

  /// 파일을 기본 앱(Preview 등)으로 연다.
  Future<void> openFile(String filePath) async {
    try {
      await Process.run('open', [filePath]);
    } catch (_) {
      // 파일 열기 실패 시 무시
    }
  }

  /// Downloads 폴더 경로를 반환한다.
  String getDownloadsPath() {
    final home = Platform.environment['HOME'] ?? '';
    return '$home/Downloads';
  }

  /// 출력 파일이 실제로 존재하는지 확인한다.
  bool outputFileExists(String path) {
    return File(path).existsSync();
  }
}
