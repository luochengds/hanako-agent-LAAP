"""LAAP Domain SDKs — Concrete domain SDK implementations.

Each subpackage implements a specific domain SDK (e.g. finquant, legal, biomed).
Every domain SDK subpackage should contain an ``sdk.py`` module with a
``DomainSDK`` class that inherits from ``laap.domain_sdk.DomainSDKBase``.

Structure::

    laap/domain_sdks/
    ├── __init__.py          (this file)
    └── finquant/            (Phase 1 — Financial Quantitative SDK)
        ├── __init__.py
        ├── sdk.py           → class DomainSDK(DomainSDKBase): ...
        ├── manifest.yaml
        ├── harness/
        ├── actors/
        ├── connectors/
        ├── species/
        ├── safety/
        └── topics.py
"""
