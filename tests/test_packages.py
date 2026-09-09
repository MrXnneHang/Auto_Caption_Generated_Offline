from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import pytest


def test_package_versions() -> None:
    """测试核心依赖版本号。"""
    from lab.__version__ import VERSION

    assert VERSION == "0.0.5", f"LAB 版本应为 0.0.5，实际为 {VERSION}"


def test_sherpa_onnx_version() -> None:
    """Check the pinned version when the optional ASR dependency is installed."""
    try:
        installed_version = version("sherpa-onnx")
    except PackageNotFoundError:
        pytest.skip("Optional sherpa-onnx dependency is not installed")
    assert installed_version == "1.10.46"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
