// 앱 전체에서 사용하는 상수 정의
// 색상, 크기, 문자열 등 하드코딩을 방지하기 위한 중앙화된 상수 파일이다.

import 'package:flutter/material.dart';

/// 앱 이름 및 버전 정보
class AppInfo {
  static const String appName = 'OCR Module';
  static const String version = '1.0.0';
  static const String githubUrl = 'https://github.com/user/OCR_Module';
}

/// 컬러 시스템 -- macOS 네이티브 느낌의 블루 계열 accent
class AppColors {
  // 메인 accent 색상 (블루 계열)
  static const Color primary = Color(0xFF007AFF);
  static const Color primaryHover = Color(0xFF0066D6);
  static const Color primaryLight = Color(0xFFE8F2FF);

  // 성공 / 에러 / 경고 색상
  static const Color success = Color(0xFF34C759);
  static const Color error = Color(0xFFFF3B30);
  static const Color warning = Color(0xFFFF9500);

  // 텍스트 색상 (Tinted Grey -- 블루 Hue 섞인 그레이)
  static const Color textPrimary = Color(0xFF1C1C1E);
  static const Color textSecondary = Color(0xFF636369);
  static const Color textTertiary = Color(0xFF8E8E93);

  // 배경 색상
  static const Color backgroundPrimary = Color(0xFFF5F7FA);
  static const Color backgroundCard = Color(0xFFFFFFFF);
  static const Color backgroundHover = Color(0xFFEEF2F8);

  // 드롭존 색상
  static const Color dropZoneBorder = Color(0xFFB8C5D6);
  static const Color dropZoneBorderActive = Color(0xFF007AFF);
  static const Color dropZoneBorderError = Color(0xFFFF3B30);
  static const Color dropZoneBackground = Color(0xFFF8FAFD);
  static const Color dropZoneBackgroundActive = Color(0xFFEBF3FF);

  // 구분선
  static const Color divider = Color(0xFFE5E9F0);
}

/// 타이포그래피 크기 시스템
class AppTextSize {
  static const double heading1 = 24.0;
  static const double heading2 = 20.0;
  static const double heading3 = 17.0;
  static const double body = 15.0;
  static const double bodySmall = 13.0;
  static const double caption = 11.0;
}

/// 간격 시스템
class AppSpacing {
  static const double xs = 4.0;
  static const double sm = 8.0;
  static const double md = 16.0;
  static const double lg = 24.0;
  static const double xl = 32.0;
  static const double xxl = 48.0;
}

/// 둥근 모서리 시스템
class AppRadius {
  static const double sm = 6.0;
  static const double md = 12.0;
  static const double lg = 16.0;
  static const double xl = 24.0;
}

/// 윈도우 크기 설정
class AppWindowSize {
  static const double minWidth = 600.0;
  static const double minHeight = 500.0;
  static const double defaultWidth = 700.0;
  static const double defaultHeight = 600.0;
}

/// 애니메이션 지속 시간
class AppDuration {
  static const Duration fast = Duration(milliseconds: 150);
  static const Duration normal = Duration(milliseconds: 250);
  static const Duration slow = Duration(milliseconds: 400);
}
