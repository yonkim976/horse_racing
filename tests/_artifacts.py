from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def requires_local_artifacts(*paths: str | Path) -> pytest.MarkDecorator:
    """Skip tests that audit git-ignored research outputs when they are not on this machine."""
    missing = [str(path) for path in paths if not (ROOT / path).exists()]
    return pytest.mark.skipif(
        bool(missing),
        reason=f"local research artifact not present: {missing[0]}" if missing else "",
    )
