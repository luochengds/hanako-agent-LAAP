"""Command-line interface for the LAAP standalone agent."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Callable, Optional, Sequence

from laap.llm.engine import (
    LLMEngine,
    MockLLMEngine,
    OllamaEngine,
    RemoteFallbackEngine,
)
from laap.standalone.agent import StandaloneAgent


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="laap-standalone",
        description="LAAP standalone agent CLI",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="One-shot task to process and exit",
    )
    parser.add_argument(
        "--local-model",
        type=str,
        default="http://localhost:11434",
        help="Base URL of the local Ollama-compatible model server",
    )
    parser.add_argument(
        "--remote-fallback",
        action="store_true",
        help="Enable remote fallback engine",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Force non-interactive mode",
    )
    return parser.parse_args(argv)


def build_agent(args: argparse.Namespace) -> StandaloneAgent:
    """Build a StandaloneAgent from parsed CLI arguments."""
    primary: LLMEngine = OllamaEngine(base_url=args.local_model)
    llm_engine: LLMEngine
    if args.remote_fallback:
        fallback: LLMEngine = MockLLMEngine(
            response="remote fallback response", name="remote-fallback"
        )
        llm_engine = RemoteFallbackEngine(primary, fallback)
    else:
        llm_engine = primary
    return StandaloneAgent(llm_engine=llm_engine)


async def run_one_shot(args: argparse.Namespace, agent: StandaloneAgent) -> int:
    """Process a single task and print the result."""
    try:
        result = await agent.process(args.task)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(result.get("response", ""))
    summary = agent.session_summary()
    print(
        f"Tokens: {summary['total_tokens']} "
        f"(local {summary['local_tokens']}, remote {summary['remote_tokens']}), "
        f"cost ${summary['estimated_cost_usd']:.4f}"
    )
    return 0


async def run_interactive(agent: StandaloneAgent) -> int:
    """Run an interactive prompt loop."""
    while True:
        try:
            user_input = input("LAAP> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        user_input = user_input.strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        result = await agent.process(user_input)
        print(result.get("response", ""))
        summary = agent.session_summary()
        print(
            f"Tokens: {summary['total_tokens']} "
            f"(local {summary['local_tokens']}, remote {summary['remote_tokens']}), "
            f"cost ${summary['estimated_cost_usd']:.4f}"
        )

    return 0


def main(
    argv: Optional[Sequence[str]] = None,
    agent_factory: Optional[Callable[[argparse.Namespace], StandaloneAgent]] = None,
) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    interactive = not args.task and not args.no_interactive
    if args.task:
        args.no_interactive = True

    agent = (agent_factory or build_agent)(args)

    if interactive:
        return asyncio.run(run_interactive(agent))
    return asyncio.run(run_one_shot(args, agent))


if __name__ == "__main__":
    sys.exit(main())
