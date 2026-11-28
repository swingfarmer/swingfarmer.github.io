#!/usr/bin/env python3
"""
mem_watch.py — VM 메모리(1GB) 범인 찾기용 매분 기록 (125)

헬스체크 「VM 메모리 (1GB)」는 하루 한 번 「지난 점검 뒤 swap으로 N MB 밀려남」만 알려 줘서
어느 시각·어느 작업이 1GB를 넘게 썼는지 모름 → 매분 /proc만 읽어(무거운 import 없음, 수 ms)
  - swap으로 밀려난 양(pswpout)이 지난 분보다 5MB 넘게 늘었거나
  - 남은 메모리(MemAvailable)가 120MB 아래면
그 시각 + 메모리 큰 프로세스 6개(RSS·실행 시간·명령)를 ~/logs/mem_watch.log에 한 묶음 남김.
평소엔 아무것도 안 씀(상태 파일 ~/sf_state/mem_watch.json만 갱신).

보는 법:  tail -40 ~/logs/mem_watch.log
"""
import os, json, time, subprocess
import re as _re

STATE = os.path.expanduser("~/sf_state/mem_watch.json")
LOG = os.path.expanduser("~/logs/mem_watch.log")
SWAP_STEP_MB = 5
LOW_AVAIL_MB = 120


def _mask(t):
    t = _re.sub(r'(https?://[^:/\s@]+:)[^@\s]+@', r'\1***@', t)
    return _re.sub(r'(ghp_|github_pat_|gho_|ghs_)[A-Za-z0-9_]+', r'\1***', t)


def read_kv(path, sep=None):
    d = {}
    with open(path) as f:
        for line in f:
            p = line.replace(":", " ").split()
            if len(p) >= 2:
                try:
                    d[p[0]] = int(p[1])
                except ValueError:
                    pass
    return d


def main():
    vm = read_kv("/proc/vmstat")
    mi = read_kv("/proc/meminfo")
    pout = vm.get("pswpout", 0)
    avail = mi.get("MemAvailable", 0) // 1024
    swap_used = (mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) // 1024
    boot = read_kv("/proc/stat").get("btime", 0)

    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    # (127) 상태 파일이 없을 때(첫 실행)는 기준만 잡고 넘어감 — 전엔 0으로 잡아 부팅 뒤 누적치를
    #       「지난 1분 동안」처럼 적었음(11/23 21:36 「+353MB」 줄). 재부팅이면 카운터가 0부터라 0이 맞음.
    if not st:
        prev = pout
    elif st.get("boot") == boot:
        prev = st.get("pout", pout)
    else:
        prev = 0
    d_mb = max(0, pout - prev) * 4096 / 1048576

    if d_mb > SWAP_STEP_MB or avail < LOW_AVAIL_MB:
        try:
            top = subprocess.run(["ps", "-eo", "rss,etime,args", "--sort=-rss"],
                                 capture_output=True, text=True, timeout=10).stdout.splitlines()[1:7]
            # (141) 명령줄에 든 비밀값 가림 — git 원격 주소의 토큰(https://이름:토큰@)·ghp_/github_pat_ 토큰
            top = [_mask(t) for t in top]
        except Exception as e:
            top = [f"(ps 실패: {e})"]
        with open(LOG, "a") as f:
            f.write(f"── {time.strftime('%Y-%m-%d %H:%M')}  swap으로 +{d_mb:.0f}MB · 여유 {avail}MB · swap 사용 {swap_used}MB\n")
            for line in top:
                p = line.split(None, 2)
                if len(p) == 3 and p[0].isdigit():
                    f.write(f"   {int(p[0])//1024:>4}MB  {p[1]:>9}  {p[2][:110]}\n")
                else:
                    f.write(f"   {line[:120]}\n")

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"pout": pout, "boot": boot, "at": time.strftime("%F %T")}, open(STATE, "w"))


if __name__ == "__main__":
    main()
