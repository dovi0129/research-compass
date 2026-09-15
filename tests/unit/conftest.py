"""pytest fixture. 가짜 엔진 구현은 `fake_engine.py` 에 있다."""
from __future__ import annotations

import pytest

from fake_engine import base_cfg, build_engine


@pytest.fixture
def engine():
    return build_engine()


@pytest.fixture
def cfg():
    return base_cfg()
