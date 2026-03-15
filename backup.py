import serial
import time
import statistics

# ──────────────────────────────────────────────
#  설정
# ──────────────────────────────────────────────
PORT = 'COM6'
BAUD = 115200
TEST_COUNT = 10                 # 반복 횟수
RX_TIMEOUT_S = 1.0              # 수신 대기 최대 시간 (초)
RX_IDLE_GAP_S = 0.04            # idle gap fallback (100 ms)
RX_TERMINATOR = b'\n'           # 종료 문자
TEST_MESSAGE = "Hello, world!Hello, world!Hello, world!Hello, world!Hello, world!Hello, world!Hello, world!Hello, world!Hello, world!Hello, world!\n"


# ──────────────────────────────────────────────
#  수신 함수
# ──────────────────────────────────────────────
def receive_echo(ser, expected_len, timeout=RX_TIMEOUT_S, terminator=b'\n'):
    """
    수신 완료 판단 (우선순위 순):
      1) 종료 문자 '\n' 감지     → 즉시 완료
      2) 예상 길이 도달           → 즉시 완료
      3) timeout                 → 안전장치
    
    ★ idle gap 제거 → USB 분할에 영향받지 않음
    """
    buf = bytearray()
    start = time.perf_counter()

    while True:
        now = time.perf_counter()
        if now - start > timeout:
            break

        waiting = ser.in_waiting
        if waiting > 0:
            buf.extend(ser.read(waiting))

            # 조건 1: 종료 문자
            if terminator and buf.endswith(terminator):
                break
            # 조건 2: 예상 길이 도달
            if len(buf) >= expected_len:
                break
        else:
            time.sleep(0.001)

    return bytes(buf)


# ──────────────────────────────────────────────
#  메인 테스트
# ──────────────────────────────────────────────
def run_echo_test():
    tx_bytes = TEST_MESSAGE.encode('utf-8')
    tx_len = len(tx_bytes)

    # 통계 수집용
    results = []           # (success: bool, latency_ms: float, rx_len: int)
    latencies = []         # 성공 케이스의 왕복 지연시간

    print("=" * 60)
    print(f"  USART Echo Test  |  {PORT} @ {BAUD} 8O1")
    print(f"  반복 횟수: {TEST_COUNT}  |  메시지 길이: {tx_len} bytes")
    print("=" * 60)

    with serial.Serial(PORT, BAUD,
                       parity=serial.PARITY_ODD,
                       stopbits=serial.STOPBITS_ONE,
                       bytesize=serial.EIGHTBITS,
                       timeout=0) as ser:

        # 포트 오픈 직후 잔여 데이터 비우기
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.1)

        for i in range(1, TEST_COUNT + 1):
            # ── Tx ──
            ser.reset_input_buffer()            # 이전 잔여 버퍼 비우기
            t_start = time.perf_counter()
            ser.write(tx_bytes)
            ser.flush()                         # 송신 완료 보장

            # ── Rx ──
            rx_bytes = receive_echo(ser, expected_len=len(tx_bytes))
            t_end = time.perf_counter()

            latency_ms = (t_end - t_start) * 1000
            rx_len = len(rx_bytes)
            success = (rx_bytes == tx_bytes)

            results.append((success, latency_ms, rx_len))
            if success:
                latencies.append(latency_ms)

            # 개별 결과 출력
            status = "OK" if success else "FAIL"
            rx_preview = rx_bytes.decode('utf-8', errors='replace').strip()
            print(f"  [{i:3d}/{TEST_COUNT}]  {status}  |  "
                  f"Rx {rx_len}/{tx_len} bytes  |  "
                  f"{latency_ms:7.2f} ms  |  {rx_preview[:50]}")

            # 연속 전송 간 짧은 간격 (MCU 안정화)
            time.sleep(0.05)

    # ──────────────────────────────────────────
    #  통계 요약
    # ──────────────────────────────────────────
    total = len(results)
    success_count = sum(1 for s, _, _ in results if s)
    fail_count = total - success_count

    print()
    print("=" * 60)
    print("  통계 요약")
    print("=" * 60)
    print(f"  전체 시도 : {total}")
    print(f"  성공      : {success_count}  ({success_count/total*100:.1f}%)")
    print(f"  실패      : {fail_count}  ({fail_count/total*100:.1f}%)")

    if latencies:
        print(f"  ──────────────────────────────────")
        print(f"  왕복 지연 (성공 케이스)")
        print(f"    평균    : {statistics.mean(latencies):7.2f} ms")
        print(f"    중앙값  : {statistics.median(latencies):7.2f} ms")
        print(f"    최소    : {min(latencies):7.2f} ms")
        print(f"    최대    : {max(latencies):7.2f} ms")
        if len(latencies) >= 2:
            print(f"    표준편차: {statistics.stdev(latencies):7.2f} ms")
    print("=" * 60)

    # 실패 상세 (있을 경우)
    failures = [(i+1, r) for i, r in enumerate(results) if not r[0]]
    if failures:
        print("\n  [실패 상세]")
        for idx, (_, lat, rx_len) in failures:
            print(f"    #{idx:3d}  Rx {rx_len}/{tx_len} bytes  |  {lat:.2f} ms")


if __name__ == '__main__':
    try:
        run_echo_test()
    except serial.SerialException as e:
        print(f"[Serial Error] {e}")
    except KeyboardInterrupt:
        print("\n[!] 사용자 중단")