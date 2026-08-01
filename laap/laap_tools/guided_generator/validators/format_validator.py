"""
Format validator — checks output format correctness using regex patterns.

Validates that generated output matches expected formats like
grammar constraints, special markers, or structural patterns.

Supports:
  - Individual AND checks (all must pass)
  - Multi-group checks: define multiple groups of patterns; a group passes
    when ALL patterns in that group match. The validator passes when at least
    one group matches (OR of AND groups).
"""

import re
from typing import Dict, List, Optional, Pattern, Tuple
from dataclasses import dataclass, field


@dataclass
class FormatCheckResult:
    """Result of a single format check."""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class FormatValidationResult:
    """Aggregated format validation result."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    checks: List[FormatCheckResult] = field(default_factory=list)


class FormatValidator:
    """
    Validates output format using regex patterns and structural checks.

    Two kinds of checks:
      1. Individual checks — all must pass (AND).
      2. Multi-groups — each group contains multiple named patterns;
         a group passes when ALL its patterns match.
         The validator passes when at least one group matches (OR of AND groups).
    """

    def __init__(self):
        # Individual (AND) checks
        self._checks: List[Tuple[str, Pattern]] = []
        # Multi-groups: each entry is a list of (name, pattern) tuples.
        # A group matches when ALL its patterns match.
        # The whole validator passes when at least one group matches.
        self._multi_groups: List[List[Tuple[str, Pattern]]] = []

    def add_regex_check(self, name: str, pattern: str) -> None:
        """Add a regex-based format check (AND logic with other checks)."""
        self._checks.append((name, re.compile(pattern)))

    def remove_check(self, name: str) -> None:
        """Remove a format check by name."""
        self._checks = [(n, p) for n, p in self._checks if n != name]

    def add_multi_group(self, group_id: str,
                        patterns: List[Tuple[str, str]]) -> None:
        """
        Add a multi-pattern group.

        A group passes when ALL its patterns match in the output.
        The overall validation passes when at least one group matches.
        Groups are evaluated independently.

        Args:
            group_id: Label for the group (for error messages).
            patterns: List of (check_name, regex_pattern).
        """
        compiled = [(name, re.compile(pat)) for name, pat in patterns]
        self._multi_groups.append((group_id, compiled))

    def validate(self, output: str) -> FormatValidationResult:
        """
        Run all registered format checks against the output.

        Returns ValidationResult with:
          - is_valid: True only if all AND checks pass AND at least one
            multi-group matches (or no multi-groups configured).
        """
        if not output:
            return FormatValidationResult(
                is_valid=False,
                errors=["Output is empty"],
                checks=[FormatCheckResult("non_empty", False, "Output is empty")],
            )

        results: List[FormatCheckResult] = []
        errors: List[str] = []

        # 1. Run individual (AND) checks
        for name, pattern in self._checks:
            if pattern.search(output):
                results.append(FormatCheckResult(name, True, "Matched"))
            else:
                msg = f"Format check '{name}' failed: pattern did not match"
                results.append(FormatCheckResult(name, False, msg))
                errors.append(msg)

        # 2. Run multi-groups (OR of ANDs)
        if self._multi_groups:
            any_group_passed = False
            for group_id, group_patterns in self._multi_groups:
                group_results: List[FormatCheckResult] = []
                group_ok = True
                for name, pattern in group_patterns:
                    if pattern.search(output):
                        group_results.append(
                            FormatCheckResult(name, True, f"[{group_id}] Matched")
                        )
                    else:
                        group_results.append(
                            FormatCheckResult(
                                name, False,
                                f"[{group_id}] Did not match"
                            )
                        )
                        group_ok = False

                if group_ok:
                    any_group_passed = True
                    results.extend(group_results)
                else:
                    # Only add individual failures if the group didn't pass
                    for r in group_results:
                        if not r.passed:
                            results.append(r)

            # Check that at least one multi-group passed
            if self._multi_groups and not any_group_passed:
                group_ids = [gid for gid, _ in self._multi_groups]
                msg = (
                    f"No multi-group matched. "
                    f"Groups tried: {', '.join(group_ids)}"
                )
                errors.append(msg)

        return FormatValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            checks=results,
        )

    @classmethod
    def with_grammar_check(cls, grammar: str) -> "FormatValidator":
        """Create a validator for GBNF grammar patterns."""
        validator = cls()
        rule_pattern = re.findall(r'^(\w+)\s*::=', grammar, re.MULTILINE)
        for rule in rule_pattern:
            if rule != "root":
                validator.add_regex_check(f"rule_{rule}", rule)
        return validator

    @classmethod
    def with_memory_ref_check(cls) -> "FormatValidator":
        """Create validator with memory reference marker checks."""
        validator = cls()
        validator.add_regex_check(
            "memory_ref",
            r'\[[a-zA-Z0-9_\-\u4e00-\u9fff]+\]',
        )
        return validator

    @classmethod
    def with_reasoning_structure(cls) -> "FormatValidator":
        """
        Create validator for reasoning chain structure.

        Accepts EITHER all three Chinese markers (思考, 分析, 结论)
        OR all three English markers (Thought, Analysis, Conclusion).
        """
        validator = cls()

        # Group A: Chinese markers (all three must match)
        validator.add_multi_group("chinese", [
            ("think_cn", r"思考[：:]"),
            ("analysis_cn", r"分析[：:]"),
            ("conclusion_cn", r"结论[：:]"),
        ])

        # Group B: English markers (all three must match)
        validator.add_multi_group("english", [
            ("think_en", r"Thought:"),
            ("analysis_en", r"Analysis:"),
            ("conclusion_en", r"Conclusion:"),
        ])

        return validator
