"""
意识工程运行时服务移植测试：
    1. 服务可启动
    2. 喂入真实事件 → 预测器/总线/记忆全链路
    3. 状态查询（当下自我/意识流/记忆统计）
    4. 夜间周期 + 验证
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

WORKDIR = Path(__file__).resolve().parent / f"_tmp_service_{int(time.time())}"
WORKDIR.mkdir(exist_ok=True)

PORT = 11535 + int(time.time()) % 100
BASE = f"http://127.0.0.1:{PORT}"
passed = 0

def check(name, cond):
    global passed
    assert cond, f"FAIL: {name}"
    passed += 1
    print(f"  [PASS] {name}")

def http_get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def http_post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

proc = None
try:
    print("=" * 72)
    print("1. 启动意识运行时服务")
    print("=" * 72)

    env = dict(os.environ)
    env["PYTHONPATH"] = r"D:\LAAP"
    proc = subprocess.Popen(
        [sys.executable, "-m", "laap.agi.consciousness_service",
         "--port", str(PORT), "--memory-db", str(WORKDIR / "mem.db")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ready = False
    for _ in range(40):
        try:
            h = http_get("/health")
            if h.get("status") == "ok":
                ready = True
                break
        except Exception:
            time.sleep(0.5)
    check("服务启动", ready)

    print("=" * 72)
    print("2. 喂入真实事件（模拟对话）")
    print("=" * 72)

    r = http_post("/consciousness/feed", {
        "event_type": "user_message",
        "content": "Lorry 说：开始移植接入意识系统",
        "source": "hanako",
    })
    check("事件被接收", "surprise" in r)
    check("产生意识焦点", len(r.get("conscious_focus", [])) > 0)
    print(f"      惊奇={r['surprise']} 焦点={r['conscious_focus']}")

    for i in range(4):
        http_post("/consciousness/feed", {
            "event_type": "user_message",
            "content": f"第 {i} 轮对话：继续完成移植工作",
            "source": "hanako",
        })
    time.sleep(0.3)

    print("=" * 72)
    print("3. 状态查询")
    print("=" * 72)

    state = http_get("/consciousness/state")
    check("当下自我快照", "present_self" in state)
    ps = state["present_self"]
    check("焦点非空", ps.get("focus", "") != "")
    print(f"      当下自我: focus={ps.get('focus')} continuity={ps.get('continuity')}")

    stream = http_get("/consciousness/stream")
    check("意识流可查询", "frames" in stream)

    mstats = http_get("/memory/stats")
    check("记忆统计", "lifecycle" in mstats)
    print(f"      记忆生命周期: {mstats['lifecycle']}")

    print("=" * 72)
    print("4. 自我审视 + RSI")
    print("=" * 72)

    review = http_get("/self/review")
    check("自我审视报告", "summary" in review or "vitals" in review)
    print(f"      审视: {review.get('summary', '')}")

    rsi = http_get("/self/rsi")
    check("RSI 建议", "rsi" in rsi)
    print(f"      RSI 建议数: {len(rsi['rsi'].get('suggestions', []))}")

    print("=" * 72)
    print("5. 验证套件")
    print("=" * 72)

    verify = http_get("/verify")
    check("验证报告生成", len(verify) > 0)
    print(f"      验证: {json.dumps(verify, ensure_ascii=False)[:250]}")

    print("=" * 72)
    print(f"移植测试全部通过: {passed} 项 ✅")
finally:
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    shutil.rmtree(WORKDIR, ignore_errors=True)
