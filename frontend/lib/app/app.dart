// 앱 루트 위젯 -- MaterialApp 설정 및 테마 정의
// 다크/라이트 모드 자동 지원, macOS 네이티브 느낌의 블루 계열 테마를 적용한다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../screens/home_screen.dart';

/// OCR Module 앱 루트 위젯
class OcrModuleApp extends StatelessWidget {
  const OcrModuleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: AppInfo.appName,
      debugShowCheckedModeBanner: false,

      // 시스템 테마 설정 자동 감지 (다크/라이트 모드)
      themeMode: ThemeMode.system,

      // 라이트 테마
      theme: _buildLightTheme(),

      // 다크 테마
      darkTheme: _buildDarkTheme(),

      home: const HomeScreen(),
    );
  }

  /// 라이트 테마를 구성한다.
  ThemeData _buildLightTheme() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.light,
        primary: AppColors.primary,
        surface: AppColors.backgroundCard,
      ),
      scaffoldBackgroundColor: AppColors.backgroundPrimary,

      // 텍스트 테마 -- macOS San Francisco 폰트와 유사한 시스템 폰트 사용
      textTheme: const TextTheme(
        headlineMedium: TextStyle(
          fontSize: AppTextSize.heading1,
          fontWeight: FontWeight.bold,
          color: AppColors.textPrimary,
        ),
        titleLarge: TextStyle(
          fontSize: AppTextSize.heading2,
          fontWeight: FontWeight.w600,
          color: AppColors.textPrimary,
        ),
        titleMedium: TextStyle(
          fontSize: AppTextSize.heading3,
          fontWeight: FontWeight.w500,
          color: AppColors.textPrimary,
        ),
        bodyLarge: TextStyle(
          fontSize: AppTextSize.body,
          color: AppColors.textPrimary,
        ),
        bodyMedium: TextStyle(
          fontSize: AppTextSize.bodySmall,
          color: AppColors.textSecondary,
        ),
        bodySmall: TextStyle(
          fontSize: AppTextSize.caption,
          color: AppColors.textTertiary,
        ),
      ),

      // 프로그레스 인디케이터 테마
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: AppColors.primary,
        linearTrackColor: AppColors.divider,
      ),

      // 버튼 테마
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
      ),

      // 구분선 테마
      dividerTheme: const DividerThemeData(
        color: AppColors.divider,
        thickness: 1,
        space: 0,
      ),
    );
  }

  /// 다크 테마를 구성한다.
  ThemeData _buildDarkTheme() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.dark,
        primary: AppColors.primary,
        surface: const Color(0xFF1A2030),
      ),
      scaffoldBackgroundColor: const Color(0xFF141822),

      // 다크 테마 텍스트
      textTheme: const TextTheme(
        headlineMedium: TextStyle(
          fontSize: AppTextSize.heading1,
          fontWeight: FontWeight.bold,
          color: Colors.white,
        ),
        titleLarge: TextStyle(
          fontSize: AppTextSize.heading2,
          fontWeight: FontWeight.w600,
          color: Colors.white,
        ),
        titleMedium: TextStyle(
          fontSize: AppTextSize.heading3,
          fontWeight: FontWeight.w500,
          color: Colors.white,
        ),
        bodyLarge: TextStyle(
          fontSize: AppTextSize.body,
          color: Colors.white70,
        ),
        bodyMedium: TextStyle(
          fontSize: AppTextSize.bodySmall,
          color: Colors.white54,
        ),
        bodySmall: TextStyle(
          fontSize: AppTextSize.caption,
          color: Colors.white38,
        ),
      ),

      // 프로그레스 인디케이터 테마
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: AppColors.primary,
        linearTrackColor: Colors.white.withAlpha(26),
      ),

      // 버튼 테마
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
      ),

      // 구분선 테마
      dividerTheme: DividerThemeData(
        color: Colors.white.withAlpha(26),
        thickness: 1,
        space: 0,
      ),
    );
  }
}
