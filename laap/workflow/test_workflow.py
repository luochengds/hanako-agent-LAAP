"""Tests for the Petri-net / actor backed workflow engine."""

import asyncio
import time

import pytest

from laap.workflow.base import Workflow, WorkflowStatus


class TestWorkflow:
    def test_existing_api_add_step_and_run(self):
        wf = Workflow(name="api_test")
        calls = []

        def step_a(value: int):
            calls.append("a")
            return value * 2

        def step_b(name: str = "world"):
            calls.append("b")
            return f"hello {name}"

        wf.add_step("a", step_a, value=3)
        wf.add_step("b", step_b)
        result = asyncio.run(wf.run())

        assert result["workflow"] == "api_test"
        assert result["status"] == "completed"
        assert result["failed"] == 0
        assert "a" in result["results"] and "6" in result["results"]["a"]
        assert "b" in result["results"] and "hello world" in result["results"]["b"]
        assert wf.status == WorkflowStatus.COMPLETED

    def test_sequential_dependency_results(self):
        wf = Workflow(name="sequential")

        def add(x: int):
            return x + 1

        def multiply(factor: int, _add_result: int):
            return _add_result * factor

        wf.add_step("add", add, x=2)
        wf.add_step("multiply", multiply, depends_on=["add"], factor=3)

        result = asyncio.run(wf.run())

        assert result["failed"] == 0
        assert result["results"]["add"] == "3"
        assert result["results"]["multiply"] == "9"

    def test_async_handlers_supported(self):
        async def fetch(x: int):
            await asyncio.sleep(0.01)
            return x + 10

        wf = Workflow(name="async")
        wf.add_step("fetch", fetch, x=5)
        result = asyncio.run(wf.run())

        assert result["failed"] == 0
        assert result["results"]["fetch"] == "15"

    def test_concurrent_independent_steps(self):
        async def slow(label: str, delay: float):
            await asyncio.sleep(delay)
            return label

        wf = Workflow(name="concurrent")
        wf.add_step("a", slow, label="A", delay=0.2)
        wf.add_step("b", slow, label="B", delay=0.2)

        start = time.perf_counter()
        result = asyncio.run(wf.run())
        elapsed = time.perf_counter() - start

        assert result["failed"] == 0
        assert result["results"]["a"] == "A"
        assert result["results"]["b"] == "B"
        # Serial execution would take ~0.4s; concurrent should be well under.
        assert elapsed < 0.35, f"expected concurrent execution < 0.35s, got {elapsed:.2f}s"

    def test_dependency_failure_blocks_downstream(self):
        wf = Workflow(name="failing_dep")

        def boom():
            raise ValueError("intentional failure")

        def downstream(_boom_result: str):
            return "never reached"

        wf.add_step("boom", boom)
        wf.add_step("downstream", downstream, depends_on=["boom"])

        result = asyncio.run(wf.run())

        assert result["failed"] == 2
        assert result["results"] == {}
        assert wf.steps["boom"].status == WorkflowStatus.FAILED
        assert wf.steps["downstream"].status == WorkflowStatus.FAILED
        assert "依赖未满足" in wf.steps["downstream"].error

    def test_missing_dependency_reported(self):
        wf = Workflow(name="missing_dep")

        def downstream(_missing_result: str):
            return "never reached"

        wf.add_step("downstream", downstream, depends_on=["missing"])

        result = asyncio.run(wf.run())

        assert result["failed"] == 1
        assert wf.steps["downstream"].status == WorkflowStatus.FAILED
        assert "依赖未满足" in wf.steps["downstream"].error

    def test_to_petri_structure(self):
        wf = Workflow(name="petri")
        wf.add_step("a", lambda: 1)
        wf.add_step("b", lambda _a_result: 2, depends_on=["a"])

        net = wf._to_petri()

        assert "start" in net.places
        assert "ready_a" in net.places
        assert "done_a" in net.places
        assert "ready_b" in net.places
        assert "done_b" in net.places
        assert "init" in net.transitions
        assert "trans_a" in net.transitions
        assert "trans_b" in net.transitions
        assert "join_b" in net.transitions
        assert "join_a" not in net.transitions

        join_b = net.transitions["join_b"]
        assert join_b.input_places == {"done_a": 1}
        assert "ready_b" in join_b.output_places

        trans_b = net.transitions["trans_b"]
        assert trans_b.input_places == {"ready_b": 1}
        assert "done_b" in trans_b.output_places


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v", "-p", "no:quadrants", "--no-cov"]))
