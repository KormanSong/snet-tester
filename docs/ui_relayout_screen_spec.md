# SNET Protocol Tester UI 재배치 Screen Spec

## 설계 원칙
- `감시`를 먼저, `제어`를 그 다음, `설정/진단`을 마지막에 둔다.
- 채널은 화면의 중심 개념으로 본다.
- 색은 상태와 경고에만 제한적으로 사용한다.
- 로그/알람은 항상 보이게 둔다.
- 운영자용 정보와 엔지니어링 정보의 깊이를 분리한다.

## 추천 레이아웃
```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ System Status                                                                               │
│ Connection | Run State | Mode | Alarm | Selected CH | Last Response | Active Recipe       │
├───────────────────────────────────────────────┬──────────────────────────────────────────────┤
│ Monitor Dashboard                             │ Work Area                                    │
│                                               │                                              │
│ 1. Overview cards                             │ 1. Operation Control                         │
│    - Selected CH                              │    - Start / Stop / Apply / Hold             │
│    - Setpoint / Actual / Valve                │    - Mode selection                          │
│    - Device health                            │    - Safe action confirmations               │
│                                               │                                              │
│ 2. Trend monitor                              │ 2. Channel Detail                            │
│    - Ratio trend                              │    - Current values                          │
│    - Valve trend                              │    - Target values                           │
│    - Limit lines / target line                │    - Preset table                            │
│                                               │    - Apply result feedback                   │
│ 3. Channel summary table                      │                                              │
│    - CH / Role / Set / Act / Valve / State    │ 3. Engineering Tabs                          │
│    - row highlight for selected channel       │    - Calibration                             │
│                                               │    - PID                                     │
│                                               │    - TX/RX Frame                             │
├───────────────────────────────────────────────┴──────────────────────────────────────────────┤
│ Alarm / Event Log                                                                            │
│ Time | Severity | Source | Message | Action Guide | Ack                                     │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 영역별 역할

### 1. System Status
- 화면 전체의 단일 상태 진실원
- 포함 항목
  - Connection: `Connected`, `Disconnected`, `No Response`
  - Run State: `Idle`, `Running`, `Hold`, `Stopped`
  - Mode: `Run`, `Calibration`, `Engineering`
  - Alarm: `Normal`, `Warning`, `Alarm`
  - Selected Channel
  - Last Response Time
  - Active Preset or Recipe

### 2. Monitor Dashboard
- 실시간 감시 중심
- 포함 항목
  - 선택 채널 카드
  - 목표값과 현재값 비교 카드
  - 장비 상태 카드
  - Trend 영역
  - 채널 요약 테이블

### 3. Work Area
- 조작과 설정 중심
- 하위 구조
  - `Operation Control`
    - 시작, 정지, 적용, 리셋, 홀드
    - 위험 동작은 강조 색과 확인창 적용
  - `Channel Detail`
    - 현재 측정값
    - 목표 비율/제어값 입력
    - 프리셋 표
    - 적용 후 피드백
  - `Engineering Tabs`
    - Calibration
    - PID
    - TX Frame
    - RX Frame

### 4. Alarm / Event Log
- 고정 노출
- 최소 컬럼
  - 시간
  - 심각도
  - 소스
  - 메시지
  - 권장 조치
  - ACK 여부

## 상태 정책
- `--` 사용 금지
  - `N/A`
  - `Disconnected`
  - `No Response`
  - `Disabled`
  - `Unknown`
  로 분리
- 읽기 전용 값과 편집 값은 배경색과 테두리로 구분
- 선택 채널은 좌측 요약표, 우측 상세패널, 상단 상태 바에서 동시에 표시

## 버튼 정책
- `Start`와 `Stop`은 인접 배치 가능하지만 색과 크기를 명확히 구분
- `Calibration`, `Save`, `Delete`, `Apply Preset`은 즉시 실행형으로 두지 않는다
- 위험 동작은 확인 대화상자 또는 이중 조작 필요

## 시각 스타일
- 배경은 밝은 회색 계열
- 상태색
  - 정상: 녹색
  - 주의: 황색/호박색
  - 경보: 적색
  - 비활성: 중간 회색
- 둥근 모서리와 그림자는 약하게 유지
- 정보 구획은 GroupBox 또는 얇은 패널 구분으로 정리

## 구현 메모
- 기존 메인 화면은 유지하되, 재배치 검증 전에는 본 화면을 직접 대수술하지 않는다.
- 먼저 별도 프리뷰 창에서 레이아웃과 용어를 검토한 뒤 기존 `main_window.ui` 반영 범위를 결정한다.
