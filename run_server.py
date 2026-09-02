from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import tomli
import uvicorn
from loguru import logger

from lab.config_manager import XnneHangLabSettings, load_settings_file

os.environ["HF_HOME"] = str(Path(__file__).parent / "models")
os.environ["MODELSCOPE_CACHE"] = str(Path(__file__).parent / "models")


def get_version() -> str:
    with Path("pyproject.toml").open("rb") as f:
        pyproject = tomli.load(f)
    return pyproject["project"]["version"]


def parse_args(lab_settings: XnneHangLabSettings):
    parser = argparse.ArgumentParser(description="XnneHangLab Server")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--port", type=int, default=lab_settings.server.port, help="Server port")
    return parser.parse_args()


def validate_config(settings: XnneHangLabSettings) -> None:
    """Validate critical runtime configuration before starting the server."""
    from lab.config_manager.validators import validate_startup

    errors, warnings = validate_startup(settings)

    if warnings:
        logger.warning("⚠️ 配置存在非阻断问题，本次启动将跳过相关 ASR 能力并继续：\n\n{}", "\n\n".join(warnings))

    if errors:
        logger.error("❌ 配置校验失败，请修复以下问题后重启：\n\n{}", "\n\n".join(errors))
        sys.exit(1)

    logger.info("✅ 配置校验通过")


@logger.catch
def run(lab_settings: XnneHangLabSettings, args: argparse.Namespace):
    """Initialize logging and start the FastAPI server."""

    from lab.logger.logger_group import init_logger
    from lab.server import WebSocketServer

    init_logger()
    server_settings = lab_settings.model_copy(
        update={"server": lab_settings.server.model_copy(update={"port": args.port})}
    )
    validate_config(server_settings)
    logger.info(f"XnneHangLab, version v{get_version()}")

    server = WebSocketServer(server_settings)

    uvicorn.run(
        app=server.app,
        host=server_settings.server.host,
        port=server_settings.server.port,
        log_level=server_settings.server.uvicorn_log_level.lower(),
        ws="websockets-sansio",
    )


if __name__ == "__main__":
    lab_settings = load_settings_file("lab.toml", XnneHangLabSettings)
    args = parse_args(lab_settings)

    run(lab_settings=lab_settings, args=args)
