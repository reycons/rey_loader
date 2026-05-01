"""
Database interaction layer for lupo_loader.

All NaviControl database calls for lupo_loader go through this module.
No raw pyodbc calls are permitted in any other app module — all
interactions go through sqlserver_utils, called from here.

Currently handles:
    Batch and BatchStep lifecycle — start, end, step logging

Will grow to include:
    Landing table load coordination (M4)
    Stored procedure orchestration (M6)

Stored procedures used:
    pIns_Batch          Create a new batch record
    pUpd_Batch_End      Stamp BatchEndDT on completion
    pIns_BatchStep      Create a new batch step record
    pUpd_BatchStep_End  Stamp BatchStepEndDT on completion
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


import pyodbc

from rey_lib.db import sqlserver_utils
from rey_lib.errors.error_utils import DatabaseError
from rey_lib.logs.log_utils import log_enter, log_exit

__all__ = [
    "SEVERITY_DEBUG",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SEVERITY_ERROR",
    "start_batch",
    "end_batch",
    "start_step",
    "end_step",
    "log_reload",
]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity level constants — match NaviControl conventions
# ---------------------------------------------------------------------------

SEVERITY_DEBUG:   int = 0      # trace detail — not shown in default views
SEVERITY_INFO:    int = 1      # normal operation steps
SEVERITY_WARNING: int = 100    # non-fatal issues
SEVERITY_ERROR:   int = 1000   # failures — visible in pGet_BatchStep filter

# ---------------------------------------------------------------------------
# Stored procedure names
# ---------------------------------------------------------------------------

_PROC_INS_BATCH:          str = "dbo.pIns_Batch"
_PROC_UPD_BATCH_END:      str = "dbo.pUpd_Batch_End"
_PROC_INS_BATCH_STEP:     str = "dbo.pIns_BatchStep"
_PROC_UPD_BATCH_STEP_END: str = "dbo.pUpd_BatchStep_End"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_batch(
    ctx: Any,
    conn: pyodbc.Connection,
    description: str,
) -> int:
    """
    Create a Batch record and return the new BatchID.

    Calls pIns_Batch with the current time as BatchStartDT.
    configID is always NULL — not used by lupo_loader.

    Parameters
    ----------
    ctx : Any
        Application context — used for logging.
    conn : pyodbc.Connection
        Open SQL Server connection to NaviControl.
    description : str
        Human-readable description of this batch run
        (e.g. 'lupo_loader: advantage ftp sync').

    Returns
    -------
    int
        The new BatchID assigned by NaviControl.

    Raises
    ------
    DatabaseError
        If the procedure call fails or returns no result.
    """
    log_enter(ctx, f"start_batch: {description}", log)
    try:
        cursor = sqlserver_utils.call_proc(
            conn,
            _PROC_INS_BATCH,
            [datetime.now(), description, None],  # BatchStartDT, description, BatchID output
        )
        try:
            row = cursor.fetchone()
            if row is None:
                raise DatabaseError(
                    f"pIns_Batch returned no BatchID for '{description}'."
                )
            batch_id = int(row[0])
        finally:
            cursor.close()

        conn.commit()
        log.info("Batch started: BatchID=%d  description=%s", batch_id, description)
        return batch_id

    except DatabaseError:
        conn.rollback()
        raise
    finally:
        log_exit(ctx, "start_batch done", log)


def end_batch(
    ctx: Any,
    conn: pyodbc.Connection,
    batch_id: int,
) -> None:
    """
    Stamp BatchEndDT on a completed batch record.

    Calls pUpd_Batch_End with the BatchID. Should be called once after
    all steps for the batch are complete — success or failure.

    Parameters
    ----------
    ctx : Any
        Application context — used for logging.
    conn : pyodbc.Connection
        Open SQL Server connection to NaviControl.
    batch_id : int
        BatchID of the batch to close.

    Raises
    ------
    DatabaseError
        If the procedure call fails.
    """
    log_enter(ctx, f"end_batch: BatchID={batch_id}", log)
    try:
        cursor = sqlserver_utils.call_proc(
            conn,
            _PROC_UPD_BATCH_END,
            [batch_id],
        )
        cursor.close()
        conn.commit()
        log.info("Batch ended: BatchID=%d", batch_id)

    except DatabaseError:
        conn.rollback()
        raise
    finally:
        log_exit(ctx, "end_batch done", log)


def start_step(
    ctx: Any,
    conn: pyodbc.Connection,
    batch_id: int,
    severity: int,
    source: str,
    message: str,
    record_count: int = 0,
    parent_step_id: Optional[int] = None,
) -> int:
    """
    Create a BatchStep record and return the new BatchStepID.

    Calls pIns_BatchStep. When parent_step_id is None the proc
    self-references the new step as its own parent, making it a
    root step. All child steps for the same operation should pass
    this root BatchStepID as their parent_step_id.

    Parameters
    ----------
    ctx : Any
        Application context — used for logging.
    conn : pyodbc.Connection
        Open SQL Server connection to NaviControl.
    batch_id : int
        BatchID this step belongs to.
    severity : int
        Severity level. Use the SEVERITY_* constants in this module.
    source : str
        Component logging this step
        (e.g. 'file_loader', 'ftp_sync', 'processor').
    message : str
        Human-readable description of what this step is doing.
    record_count : int
        Number of records processed in this step. Defaults to 0.
    parent_step_id : Optional[int]
        Parent BatchStepID. Pass None for the root step of an operation.
        Pass the root step ID for all child steps.

    Returns
    -------
    int
        The new BatchStepID assigned by NaviControl.

    Raises
    ------
    DatabaseError
        If the procedure call fails or returns no result.
    """
    log_enter(ctx, f"start_step: {source} — {message}", log)
    try:
        cursor = sqlserver_utils.call_proc(
            conn,
            _PROC_INS_BATCH_STEP,
            [batch_id, severity, source, message, record_count, parent_step_id],
        )
        try:
            row = cursor.fetchone()
            if row is None:
                raise DatabaseError(
                    f"pIns_BatchStep returned no BatchStepID for "
                    f"BatchID={batch_id} source='{source}'."
                )
            step_id = int(row[0])
        finally:
            cursor.close()

        conn.commit()
        log.debug(
            "BatchStep started: BatchStepID=%d  BatchID=%d  severity=%d  source=%s",
            step_id, batch_id, severity, source,
        )
        return step_id

    except DatabaseError:
        conn.rollback()
        raise
    finally:
        log_exit(ctx, "start_step done", log)


def end_step(
    ctx: Any,
    conn: pyodbc.Connection,
    step_id: int,
) -> None:
    """
    Stamp BatchStepEndDT on a completed batch step record.

    Calls pUpd_BatchStep_End with the BatchStepID. Should be called
    immediately after the work for that step is complete.

    Parameters
    ----------
    ctx : Any
        Application context — used for logging.
    conn : pyodbc.Connection
        Open SQL Server connection to NaviControl.
    step_id : int
        BatchStepID of the step to close.

    Raises
    ------
    DatabaseError
        If the procedure call fails.
    """
    log_enter(ctx, f"end_step: BatchStepID={step_id}", log)
    try:
        cursor = sqlserver_utils.call_proc(
            conn,
            _PROC_UPD_BATCH_STEP_END,
            [step_id],
        )
        cursor.close()
        conn.commit()
        log.debug("BatchStep ended: BatchStepID=%d", step_id)

    except DatabaseError:
        conn.rollback()
        raise
    finally:
        log_exit(ctx, "end_step done", log)


def log_reload(
    ctx: Any,
    batch_conn: pyodbc.Connection,
    file_path: Path,
    original_batch_id: Optional[int],
    new_batch_id: Optional[int],
) -> None:
    """
    Log BatchStep records on both batches when a file is being reloaded.

    Called via the on_reload callback when file_loader detects that a
    file's rows already exist in staging. Adds a step to the original
    batch noting it is being superseded, closes the original batch, then
    adds a step to the new batch noting it is a reload.

    Parameters
    ----------
    ctx : Any
        Application context — used for logging.
    batch_conn : pyodbc.Connection
        Open SQL Server connection to NaviControl.
    file_path : Path
        File being reloaded.
    original_batch_id : Optional[int]
        BatchID that originally loaded the file.
    new_batch_id : Optional[int]
        BatchID of the current reload run.
    """
    log_enter(ctx, f"log_reload: {file_path.name}", log)

    try:
        # Step on original batch — note it is being superseded.
        if original_batch_id is not None:
            start_step(
                ctx,
                batch_conn,
                batch_id=original_batch_id,
                severity=SEVERITY_WARNING,
                source="file_loader",
                message=(
                    f"File '{file_path.name}' reloaded by BatchID={new_batch_id}. "
                    f"Staging rows deleted and reloaded under new batch."
                ),
                record_count=0,
            )
            end_batch(ctx, batch_conn, original_batch_id)
            log.warning(
                "Original batch closed: BatchID=%d superseded by BatchID=%s",
                original_batch_id, new_batch_id,
            )

        # Step on new batch — note it is a reload.
        if new_batch_id is not None:
            start_step(
                ctx,
                batch_conn,
                batch_id=new_batch_id,
                severity=SEVERITY_WARNING,
                source="file_loader",
                message=(
                    f"Reload of '{file_path.name}'. "
                    f"Previously loaded in BatchID={original_batch_id} — "
                    f"staging rows were deleted and file is being reloaded."
                ),
                record_count=0,
            )

    finally:
        log_exit(ctx, "log_reload done", log)
