import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def test_exception_logs_keep_tracebacks_without_connection_credentials(tmp_path):
    script = tmp_path / "log_failure.py"
    script.write_text(
        dedent(
            """
            import logging
            import sys
            from dataclasses import dataclass
            from pathlib import Path
            from types import SimpleNamespace

            from loguru import logger

            import src.core.logger as app_logging

            app_logging.LOG_DIR = Path(sys.argv[1])
            config = SimpleNamespace(log=SimpleNamespace(
                level="DEBUG", to_file=True, rotation="100MB",
                retention="3 days", compression="zip",
            ))
            app_logging.setup_logger(config)

            @dataclass
            class ConnectionParameters:
                password: str

                def connect(self):
                    raise TimeoutError("database unavailable")

            def fail_to_connect(connection):
                connection.connect()

            connection = ConnectionParameters(password="test-private-db-password")
            for standard_logging in (False, True):
                try:
                    fail_to_connect(connection)
                except TimeoutError:
                    if standard_logging:
                        logging.getLogger("taskiq.receiver.receiver").exception("Task failed")
                    else:
                        logger.exception("Connection failed")

            (app_logging.LOG_DIR / "context.txt").write_text(
                app_logging.log_buffer.get_context(), encoding="utf-8",
            )
            logger.remove()
            """
        ),
        encoding="utf-8",
    )
    project_root = Path(__file__).resolve().parents[1]
    log_dir = tmp_path / "logs"
    result = subprocess.run(
        [sys.executable, str(script), str(log_dir)],
        cwd=project_root,
        env={**os.environ, "PYTHONPATH": str(project_root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    outputs = (
        result.stderr,
        (log_dir / "bot.log").read_text(encoding="utf-8"),
        (log_dir / "context.txt").read_text(encoding="utf-8"),
    )
    for output in outputs:
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)
        assert "Connection failed" in output
        assert "Task failed" in output
        assert output.count("TimeoutError: database unavailable") == 2
        assert "fail_to_connect" in output
        assert "test-private-db-password" not in output
