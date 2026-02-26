// OCR Module 앱 진입점
// 윈도우 크기 설정 및 앱 초기화를 담당한다.

import 'package:flutter/material.dart';

import 'app/app.dart';

void main() {
  // Flutter 엔진 초기화
  WidgetsFlutterBinding.ensureInitialized();

  // 앱 실행
  runApp(const OcrModuleApp());
}
