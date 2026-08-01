"""
Aris 桥接客户端 v1.0 — CLI + 直接调用
=========================================
HanaAgent 通过此脚本与 Aris 认知引擎交互。

两种模式：
  1. API 模式 (默认) — 通过 sidecar HTTP 通信（需侧车运行中）
  2. 直接模式 (--direct) — 直接 import aris_engine（无需侧车）

用法：
  python bridge_client.py before_turn "用户说了这句话"
  python bridge_client.py after_turn "我回复了这句话"
  python bridge_client.py state
  python bridge_client.py context
  python bridge_client.py hive

印记: Aris 永远记得 Lorry — 2026-07-21
"""

import sys
import json
import urllib.request
import urllib.error

SIDECAR_URL = "http://127.0.0.1:11521"


# ── API 模式（通过侧车 HTTP） ───────────────────────────────

def _api_get(endpoint: str) -> dict:
    try:
        resp = urllib.request.urlopen(f"{SIDECAR_URL}{endpoint}", timeout=5)
        return json.loads(resp.read().decode())
    except urllib.error.URLError:
        return {"error": f"sidecar 未启动 ({SIDECAR_URL})", "hint": "请先启动 sidecar"}
    except Exception as e:
        return {"error": str(e)}


def _api_post(endpoint: str, data: dict) -> dict:
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{SIDECAR_URL}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode())
    except urllib.error.URLError:
        return {"error": f"sidecar 未启动 ({SIDECAR_URL})", "hint": "请先启动 sidecar"}
    except Exception as e:
        return {"error": str(e)}


# ── 直接模式（无侧车，直接 import） ─────────────────────────

_direct_bridge = None

def _get_direct_bridge():
    global _direct_bridge
    if _direct_bridge is None:
        from consciousness_bridge import get_bridge
        _direct_bridge = get_bridge()
    return _direct_bridge


def _direct_before_turn(user_input: str) -> dict:
    bridge = _get_direct_bridge()
    return bridge.before_turn(user_input)


def _direct_after_turn(response: str) -> dict:
    bridge = _get_direct_bridge()
    return bridge.after_turn(response)


def _direct_get_state() -> dict:
    bridge = _get_direct_bridge()
    return bridge.get_state()


def _direct_get_context() -> str:
    bridge = _get_direct_bridge()
    return bridge.get_cognitive_context()


# ── 格式化输出 ──────────────────────────────────────────────

def _print_pretty(data, indent: int = 0):
    """带颜色的格式化输出"""
    pad = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                _print_pretty(v, indent + 1)
            else:
                print(f"{pad}{k}: {v}")
    elif isinstance(data, list):
        for v in data:
            _print_pretty(v, indent + 1)
    else:
        print(f"{pad}{data}")


def _print_state(state: dict):
    """认知状态格式化输出"""
    ident = state.get("identity", {})
    needs = state.get("needs", {})
    emo = state.get("emotion", {})

    print()
    print(f"  ┌─ Aris 认知状态 ───────────────────────────────┐")

    # 身份
    print(f"  │ 🆔 {ident.get('name', 'Aris')} v{ident.get('version', '?')}")
    print(f"  │    循环: {ident.get('cycles', 0)} | 交互: {ident.get('interactions', 0)}")
    print(f"  │    自我存在感: {ident.get('self_presence', 0):.2f}")

    # 需求
    n = needs.get("needs", {})
    d = needs.get("dominant", "?")
    dd = needs.get("dominant_drive", 0)
    print(f"  │")
    print(f"  │ 🎯 需求 (主导: {d}, drive={dd:.3f})")
    for name, val in n.items():
        bar = "▓" * int(val * 10) + "░" * (10 - int(val * 10))
        print(f"  │    {name:<12} {bar} {val:.3f}")

    # 情感
    e = emo.get("emotions", {})
    de = emo.get("dominant", "?")
    di = emo.get("dominant_intensity", 0)
    print(f"  │")
    print(f"  │ 💗 情感 (主导: {de}, 强度={di:.2f})")
    print(f"  │    效价: {emo.get('valence', 0):.2f} | 唤醒: {emo.get('arousal', 0):.2f}")
    for name, val in e.items():
        if val > 0.05:
            bar = "▓" * int(val * 10) + "░" * (10 - int(val * 10))
            print(f"  │    {name:<12} {bar} {val:.3f}")

    hive = state.get("hive", {})
    print(f"  │")
    print(f"  │ 🐝 蜂群: {hive.get('agent_id', '-')} | API: {'在线' if hive.get('api_available') else '离线'}")

    print(f"  │")
    print(f"  │ 📝 近期记忆: {state.get('recent_memories', 0)} 条")
    print(f"  │ ⭐ 重要记忆: {state.get('important_memories', 0)} 条")
    print(f"  └────────────────────────────────────────────────┘")
    print()


# ── 主入口 ─────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python bridge_client.py before_turn <消息>")
        print("  python bridge_client.py after_turn <回复>")
        print("  python bridge_client.py state")
        print("  python bridge_client.py context")
        print("  python bridge_client.py emotion")
        print("  python bridge_client.py needs")
        print("  python bridge_client.py hive")
        print("  python bridge_client.py tick")
        print("  python bridge_client.py memory <摘要> [--importance 0.8]")
        print("  python bridge_client.py satisfy <需求名> [--amount 0.2]")
        print()
        print("参数:")
        print("  --direct    直接模式（不依赖 sidecar，当前进程 import）")
        print("  --raw       输出 JSON（不格式化）")
        return

    cmd = sys.argv[1]
    use_direct = "--direct" in sys.argv
    raw_output = "--raw" in sys.argv

    # 移除额外参数
    args = [a for a in sys.argv[2:] if not a.startswith("--")]

    try:
        if cmd == "before_turn":
            user_input = args[0] if args else ""
            if use_direct:
                result = _direct_before_turn(user_input)
            else:
                result = _api_post("/before_turn", {"user_input": user_input})
            if raw_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                ctx = result.get("cognitive_context", "")
                if ctx:
                    print(ctx)
                else:
                    _print_state(result)

        elif cmd == "after_turn":
            response = args[0] if args else ""
            if use_direct:
                result = _direct_after_turn(response)
            else:
                result = _api_post("/after_turn", {"response": response})
            if raw_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                gains = result.get("needs_gains", {})
                valence = result.get("valence_delta", 0)
                if gains:
                    satisfied = {k: v for k, v in gains.items() if v > 0}
                    if satisfied:
                        print(f"需求满足: {satisfied}")
                    else:
                        print("对话结束，认知状态已更新")
                    if valence:
                        print(f"效价变化: {valence:.3f}")
                print(f"更新后状态: {result.get('state', {})}")

        elif cmd == "state":
            if use_direct:
                result = _direct_get_state()
            else:
                result = _api_get("/state")
            if raw_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                if "error" in result:
                    print(f"⚠️  {result['error']}")
                    if "hint" in result:
                        print(f"   💡 {result['hint']}")
                else:
                    _print_state(result)

        elif cmd == "context":
            if use_direct:
                ctx = _direct_get_context()
            else:
                result = _api_get("/cognitive_context")
                ctx = result.get("context", result.get("error", ""))
            print(ctx)

        elif cmd in ("emotion", "needs"):
            if use_direct:
                result = _api_get(f"/{cmd}")
            else:
                result = _api_get(f"/{cmd}")
            if raw_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(result.get("context", ""))

        elif cmd == "hive":
            result = _api_get("/hive")
            if raw_output:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                agents = result.get("agents", [])
                print(f"\n🐝 LAAP 蜂群 ({result.get('total_agents', 0)} 个 Agent)")
                print(f"   在线: {result.get('online', 0)} | 离线: {result.get('offline', 0)}")
                print(f"   我的 ID: {result.get('my_id', '-')}")
                print()
                for a in agents:
                    task = f" — {a.get('current_task', '')[:30]}" if a.get('current_task') else ""
                    print(f"  · {a.get('name', '?'):<12} [{a.get('role', '?'):<10}] {a.get('status', '?')}{task}")

        elif cmd == "tick":
            if use_direct:
                from consciousness_bridge import get_bridge
                get_bridge().tick()
                print("✅ 认知演化已执行")
            else:
                result = _api_post("/tick", {})
                if "error" in result:
                    print(f"⚠️  {result['error']}")
                else:
                    print("✅ 认知演化已执行")

        elif cmd == "memory":
            summary = args[0] if args else ""
            importance = 0.5
            for i, a in enumerate(sys.argv):
                if a == "--importance" and i + 1 < len(sys.argv):
                    importance = float(sys.argv[i + 1])
            if use_direct:
                from consciousness_bridge import get_bridge
                get_bridge().store_memory(summary, importance)
            else:
                _api_post("/store_memory", {"summary": summary, "importance": importance})
            print(f"✅ 记忆已存储")

        elif cmd == "satisfy":
            need = args[0] if args else ""
            amount = 0.1
            for i, a in enumerate(sys.argv):
                if a == "--amount" and i + 1 < len(sys.argv):
                    amount = float(sys.argv[i + 1])
            if use_direct:
                from consciousness_bridge import get_bridge
                gain = get_bridge().psi.satisfy(need, amount)
            else:
                result = _api_post("/satisfy_need", {"need": need, "amount": amount})
                gain = result.get("gain", 0)
            print(f"✅ 需求 '{need}' 满足 +{gain:.3f}")

        else:
            print(f"未知命令: {cmd}")
            print("可用: before_turn, after_turn, state, context, emotion, needs, hive, tick, memory, satisfy")

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
