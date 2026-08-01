"""LAAP — Native file-content search tool."""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Dict, List


class SearchTool:
    """Regex search across files under a root directory."""

    @staticmethod
    def search_files(
        pattern: str,
        root: str = ".",
        glob: str = "*.py",
        max_results: int = 20,
    ) -> List[Dict[str, object]]:
        """Walk *root* and return matches ranked by a simple score.

        Each result contains ``path``, ``line``, ``snippet``, and ``score``.
        """
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return [{"error": f"Invalid regex: {exc}"}]

        results: List[Dict[str, object]] = []
        root_path = Path(root)

        for dirpath, _, filenames in os.walk(root_path):
            for filename in filenames:
                if not fnmatch.fnmatch(filename, glob):
                    continue
                file_path = Path(dirpath) / filename
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                for line_no, line in enumerate(text.splitlines(), start=1):
                    match = regex.search(line)
                    if match:
                        score = 1.0 + (0.5 if match.group(0) == line.strip() else 0.0)
                        results.append(
                            {
                                "path": str(file_path),
                                "line": line_no,
                                "snippet": line.strip(),
                                "score": score,
                            }
                        )
                        if len(results) >= max_results:
                            return results
        return results
