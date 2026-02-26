// 홈 화면의 OCR 이벤트 처리 로직
// OcrEvent 스트림을 받아 상태 변수를 업데이트하는 핸들러 함수들을 정의한다.
// home_screen.dart 의 크기를 줄이기 위해 분리한 파일이다.

import '../models/ocr_state.dart';

/// OCR 이벤트 처리 로직의 공통 헬퍼 모음
class HomeStateHandler {
  /// Python progress status 값을 한국어로 변환한다.
  static String translateProgressStatus(String? status) {
    switch (status) {
      case 'extracting_image':
        return '이미지 추출 중';
      case 'ocr_processing':
        return 'OCR 추론 중';
      case 'writing_output':
        return 'PDF 생성 중';
      case 'page_complete':
        return '페이지 완료';
      default:
        return '처리 중...';
    }
  }

  /// Python download status 값을 한국어로 변환한다.
  static String translateDownloadStatus(String? status) {
    switch (status) {
      case 'downloading':
        return '다운로드 중';
      case 'verifying':
        return '무결성 검증 중';
      case 'extracting':
        return '압축 해제 중';
      default:
        return '준비 중...';
    }
  }

  /// 현재 앱 상태에 맞는 헤더 설명 문구를 반환한다.
  static String getStateDescription(OcrAppState state) {
    switch (state) {
      case OcrAppState.idle:
        return 'PDF를 검색 가능한 텍스트로 변환';
      case OcrAppState.fileSelected:
        return '파일 선택 완료';
      case OcrAppState.downloadingModel:
        return 'AI 모델 다운로드 중...';
      case OcrAppState.processing:
        return 'OCR 처리 중...';
      case OcrAppState.complete:
        return '변환 완료';
      case OcrAppState.error:
        return '오류 발생';
    }
  }
}
