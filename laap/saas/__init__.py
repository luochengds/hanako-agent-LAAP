"""LAAP SaaS — 自演化业务系统 (Self-Growing SaaS)

LAAP 2.0 L3: 自演化 SaaS 运行时

让 LAAP 能力通过 Web 页面暴露, 支持:
- LAAP-UI 协议动态渲染为 HTML
- REST API 自动生成 (基于数据模型)
- 多租户隔离 + 角色权限
- 用户行为追踪 → 模式识别 → 功能自动生成
- 灰度部署 + 安全回滚

Phase 1: SaaS Runtime (Foundation)
  - LAAP-UI → HTML Renderer
  - FastAPI Server + REST API
  - Dynamic Data Model Store
  - Multi-tenant + Auth

Phase 2: Self-Growth Engine (Coming)
  - Behavior Tracker → Pattern Mining → Feature Generation
  - Safe Code Sandbox + Canary Deploy

Phase 3: Autonomous Optimization (Coming)
  - Cross-feature Integration
  - Third-party API Auto-connect
  - System Self-Optimization
"""

from laap.saas.server.app import create_app, run_server

__version__ = "0.1.0"
__all__ = ["create_app", "run_server"]
