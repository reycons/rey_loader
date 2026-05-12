"""Sync stage for rey_loader.

Invokes the ftp_sync process as a subprocess. All configuration — python
interpreter path, script path, and default args — is read from
ctx.stages.ftp_sync. No paths or arguments are hardcoded here.
"""

from __future__ import annotations

import logging
import os
import subprocess

from pathlib import Path
from rey_lib.config.config_utils import Namespace
from rey_lib.errors.error_utils import AppError

__all__ = ["run_sync"]

_logger = logging.getLogger(__name__)


def run_sync(ctx: Namespace) -> None:
    """Run the ftp_sync stage as a subprocess.

    Reads ctx.stages.ftp_sync for the python executable, script path, and
    default args. Appends ctx.env at runtime. Raises AppError on non-zero exit.

    Parameters
    ----------
    ctx : Namespace
        Application context built by build_ctx().
        ctx.stages.ftp_sync must be configured.

    Raises
    ------
    AppError
        If ctx.stages.ftp_sync is not configured or ftp_sync exits non-zero.
    """
    ftp_cfg = getattr(getattr(ctx, "stages", None), "ftp_sync", None)
    if ftp_cfg is None:
        raise AppError(
            "ctx.stages.ftp_sync is not configured. "
            "Check config/app/stages.yaml."
        )

    # Build the command from config — no hardcoded paths or args.
    cmd = [
        str(ftp_cfg.python),
        str(ftp_cfg.script),
        *[str(a) for a in (getattr(ftp_cfg, "args", None) or [])],
        ctx.env,
    ]

    _logger.info("Running ftp_sync: %s", " ".join(cmd))
    script_path = Path(str(ftp_cfg.script))

    env = os.environ.copy()
    env.pop("APP_CONFIG_DIR", None)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=script_path.parent,
        env=env,
    )


    if result.returncode != 0:
        _logger.error("ftp_sync stderr:\n%s", result.stderr)
        raise AppError(
            f"ftp_sync exited with code {result.returncode}. "
            "See log for stderr output."
        )

    _logger.info("Sync stage complete.")
