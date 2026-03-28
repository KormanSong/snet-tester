# 절대지침: Designer-Runtime UI 일치성 (UI Consistency Directive)

> **등급**: P0 — 모든 Phase, 모든 작업에서 최우선 준수
> **제정일**: 2026-03-28
> **적용 범위**: snet_tester/views/*.py, resources/ui/*.ui

---

## 원칙

**Qt Designer에서 보이는 화면과 런타임 프로그램의 화면은 반드시 일치해야 한다.**

---

## 규칙

### 규칙 1: 정적 UI 속성은 반드시 .ui 파일에 정의한다

다음 속성은 Python 코드에서 설정하지 않는다:

- `setMinimumWidth/Height/Size`, `setMaximumWidth/Height/Size`, `setFixedWidth/Height/Size`
- `setSizePolicy`
- `setFont`
- `setContentsMargins`, `setSpacing`
- `setGeometry`, `resize`
- `setStyleSheet` (정적 초기값)

### 규칙 2: Python에서 허용되는 UI 설정

다음 경우에만 Python에서 UI 속성을 설정할 수 있다:

| 허용 사유 | 예시 | 필수 주석 |
|-----------|------|-----------|
| **동적 상태 변경** | dirty/clean 스타일 토글, RUN/STOP 배지 | 불필요 |
| **Qt Designer 미지원 속성** | `setStretch()`, `QHeaderView.setSectionResizeMode()` | `# ui-override: Designer 미지원` |
| **Python 전용 위젯** | pyqtgraph PlotWidget, 커스텀 위젯 | `# ui-override: Python 전용 위젯` |
| **런타임 데이터 의존** | setText(), setToolTip() (수신 데이터) | 불필요 |

### 규칙 3: 예외 사항에는 반드시 주석을 단다

Python에서 .ui 위젯의 정적 속성을 설정해야 하는 경우:

```python
# ui-override: <사유>
widget.setMinimumHeight(320)
```

`# ui-override:` 주석이 없는 정적 UI 속성 설정은 위반으로 간주한다.

### 규칙 4: 위젯 동적 생성 최소화

- .ui에 없는 위젯을 Python에서 생성하는 것은 최후의 수단
- 동적 생성이 불가피한 경우 `# ui-dynamic: <사유>` 주석 필수

---

## 현재 알려진 위반 사항 (이관 대상)

| 파일 | 내용 | 상태 |
|------|------|------|
| main_window.py:161-162 | calibrationGroup 크기/정책 | .ui 이관 필요 |
| main_window.py:167-168 | central_layout.setStretch(0,5)/(1,2) | Designer 미지원 — EXEMPT |
| main_window.py:279-280 | debugTabWidget 크기/정책 덮어쓰기 | .ui 이관 필요 |
| plot_view.py:277,296 | PlotWidget minHeight | Python 전용 위젯 — EXEMPT |
| plot_view.py:324-325 | plotHost layout stretch | Designer 미지원 — EXEMPT |
| plot_view.py:416-442 | 토글 버튼 스타일/폰트/높이 | 동적 채널색 계산 — EXEMPT |
| tx_panel.py:539-541 | 프리셋 테이블 헤더 리사이즈 | Designer 미지원 — EXEMPT |

---

## 검증 프로세스

### 자동 검증 (모든 커밋 전)

1. **정적 분석**: views/*.py에서 `# ui-override:` 없이 정적 UI 속성을 설정하는 코드 탐지
2. **런타임 비교**: .ui만 로드한 상태 vs 앱 초기화 후 상태의 위젯 속성 차이 비교

### 수동 검증 (Phase 완료 시)

5단계 검증 체크리스트의 **4단계(Designer 일치)**를 최우선으로 실행:
1. `uv run snet-designer` 실행 → Designer에서 main_window.ui 열기
2. `uv run python -m snet_tester --mock` 실행
3. 두 화면을 나란히 놓고 비교:
   - 패널 크기 비율
   - 테이블 행/열 크기
   - 폰트, 여백, 간격
   - 버튼 크기와 위치
4. 불일치 항목 기록 → .ui 이관 또는 `# ui-override:` 주석 추가
