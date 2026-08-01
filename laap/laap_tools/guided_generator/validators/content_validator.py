"""
Content validator — checks content quality and implements retry logic.

Validates that generated content is non-empty, sufficiently long,
and meets basic quality criteria.
"""

import time
import logging
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("guided_generator")


@dataclass
class ContentValidationResult:
    """Result of content quality validation."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    retry_count: int = 0
    all_outputs: List[str] = field(default_factory=list)


class ContentValidator:
    """
    Validates content quality: length, emptiness, coherence.
    Includes retry logic for failed validation.
    """

    def __init__(
        self,
        min_length: int = 3,
        max_length: int = 10000,
        reject_empty: bool = True,
        reject_repetitive: bool = True,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.reject_empty = reject_empty
        self.reject_repetitive = reject_repetitive

    def validate(self, output: str) -> ContentValidationResult:
        """
        Perform content quality checks on the output.
        Returns (is_valid, errors).
        """
        errors: List[str] = []

        # Empty check
        if self.reject_empty and not output.strip():
            errors.append("Output is empty or whitespace-only")

        # Length checks
        if len(output.strip()) < self.min_length:
            errors.append(
                f"Output too short: {len(output.strip())} chars "
                f"(min {self.min_length})"
            )

        if len(output) > self.max_length:
            errors.append(
                f"Output too long: {len(output)} chars "
                f"(max {self.max_length})"
            )

        # Repetitive pattern check
        if self.reject_repetitive:
            # Check for excessive repetition (same word 5+ times in a row)
            words = output.split()
            if len(words) >= 5:
                for i in range(len(words) - 4):
                    if len(set(words[i:i+5])) == 1:
                        errors.append(
                            f"Output contains repetitive pattern: "
                            f"'{words[i]}' repeated 5+ times"
                        )
                        break

        return ContentValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
        )

    def validate_with_retry(
        self,
        generate_fn: Callable[[], str],
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> ContentValidationResult:
        """
        Generate content with retry on validation failure.

        Args:
            generate_fn: A callable that returns generated text.
            max_retries: Maximum number of generation attempts.
            retry_delay: Seconds to wait between retries.

        Returns:
            ContentValidationResult with all attempts recorded.
        """
        all_outputs: List[str] = []
        all_errors: List[str] = []

        for attempt in range(max_retries + 1):
            logger.debug(f"Generation attempt {attempt + 1}/{max_retries + 1}")

            output = generate_fn()
            all_outputs.append(output)

            result = self.validate(output)
            if result.is_valid:
                return ContentValidationResult(
                    is_valid=True,
                    errors=[],
                    retry_count=attempt,
                    all_outputs=all_outputs,
                )

            all_errors.extend(result.errors)
            logger.debug(f"Attempt {attempt + 1} failed: {result.errors}")

            if attempt < max_retries:
                time.sleep(retry_delay)

        # All attempts failed — return last result with all errors
        return ContentValidationResult(
            is_valid=False,
            errors=all_errors,
            retry_count=max_retries,
            all_outputs=all_outputs,
        )
