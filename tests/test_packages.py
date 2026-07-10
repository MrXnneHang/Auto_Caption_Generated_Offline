from __future__ import annotations

from importlib.metadata import version

import pytest


def test_package_versions() -> None:
    """测试核心依赖版本号。"""
    from lab.__version__ import VERSION

    assert VERSION == "0.0.5", f"LAB 版本应为 0.0.5，实际为 {VERSION}"
    assert version("sherpa-onnx") == "1.10.46"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
