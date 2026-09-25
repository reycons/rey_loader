"""Load stage for rey_loader.

Delegates entirely to rey_lib.files.file_loader.run_load. Connection
management, bulk insert, file movements, hooks, and post_load_sql are
all handled by rey_lib — DB calls inside rey_lib now route through
DBAdapter, so this module stays backend-agnostic. Connection details
are read from each load config's load.connection field in the data
source YAML.
"""

from __future__ import annotations

from pathlib import Path

from typing import Any

from rey_lib.config.config_utils import Namespace
from rey_lib.load.load_operation import load_file_to_table as _load_file_to_table
from rey_lib.load.load_operation import load_one as _load_one
from rey_lib.load.load_operation import (
    load_query_to_file as _load_query_to_file,
)
from rey_lib.load.load_operation import (
    load_query_to_table as _load_query_to_table,
)
from rey_lib.load.load_operation import run_load as _run_load
from rey_lib.logs import get_logger

from rey_loader.error_utils import ReyLoaderError

__all__ = ["run_load", "run_load_direct", "run_load_one"]

_logger = get_logger(__name__)

def run_load(ctx: Namespace) -> int:
    """Run the load stage for all configured data sources.

    Delegates to rey_lib.files.file_loader.run_load. All connection
    management, bulk insert, file movements, hook dispatch, and
    post_load_sql execution are handled by rey_lib — no
    application-specific code here.

    Parameters
    ----------
    ctx : Namespace
        Application context built by build_ctx().

    Returns
    -------
    int
        Total number of rows loaded across all data sources.
    """
    total = _run_load(ctx, sql_dir=ctx.sql_dir)
    _logger.info("Load stage complete: %d row(s) loaded.", total)
    return total


def run_load_direct(
    ctx: Namespace,
    run_log,
    file_path: Path,
    destination: str,
    connection: str,
    *,
    create_destination: bool = False,
    file_type: str = "",
) -> int:
    """Load one named file into one named table. No configured data source.

    The arguments say everything a load needs, so nothing is read from
    configuration and nothing is manufactured to stand in for it. The object
    graph is the same one a configured feed runs -- a DataFile for the
    format, an IdentityTransform, a DataLoader for the destination -- built
    from arguments instead of YAML.

    Parameters
    ----------
    file_path : Path
        The file to load.
    destination : str
        ``schema.table``, or ``database.schema.table`` where the backend
        qualifies that way.
    connection : str
        Name of a configured connection. Only the CONNECTION comes from
        configuration: it is a credential and a host, not a load definition.
    create_destination : bool
        Whether an absent table may be created from the file.
    file_type : str
        The format, where the suffix does not name one.

    Returns
    -------
    int
        Rows loaded.

    Raises
    ------
    ReyLoaderError
        If the file does not exist.
    """
    if not file_path.is_file():
        raise ReyLoaderError(f"load --file: no such file: {file_path}")

    # The NAME is passed, not a handle. The load builds its target from it and
    # opens a connection from that target, so where the destination lives is
    # said once rather than resolved here and named again below.
    _logger.info("Loading %s directly into %s via '%s'",
                 file_path.name, destination, connection)
    total = _load_file_to_table(
        ctx, run_log, file_path, destination, connection,
        create_destination=create_destination, file_type=file_type,
    )
    _logger.info("Load complete: %d row(s) loaded.", total)
    return total


def run_load_query(
    ctx: Namespace,
    run_log,
    statement: str,
    source_connection: str,
    destination: str,
    connection: str,
    *,
    create_destination: bool = False,
    transform: Any = None,
) -> int:
    """Load what one statement returns into one named table.

    The database sibling of ``run_load_direct``, and the same kind of wrapper:
    it logs what is being loaded and where, calls the library, and logs the
    count. The load itself is ``rey_lib``'s.

    TWO CONNECTIONS, AND THEY MAY DIFFER. The statement runs on one and the
    destination lives on the other; both are configured NAMES rather than
    handles, and the library opens each where it is needed. A load between
    two databases is the case this exists for, so nothing here assumes they
    are the same.

    Parameters
    ----------
    statement : str
        The SQL whose result is loaded. Passed as written -- nothing here
        parses it, rewrites it, or decides what it means.
    source_connection : str
        Name of the configured connection the statement runs on.
    destination : str
        ``schema.table``, or ``database.schema.table`` where the backend
        qualifies that way.
    connection : str
        Name of the configured connection the DESTINATION lives on.
    create_destination : bool
        Whether an absent table may be created from the records.
    transform : Any
        A transform declaration. Absent means the rows are loaded as the
        query returned them.

    Returns
    -------
    int
        Rows loaded.

    Raises
    ------
    ReyLoaderError
        If the statement is empty. Refused here for the same reason
        ``run_load_direct`` refuses a missing file: an empty source is a
        mistyped invocation, and letting it reach the database turns it into
        a syntax error from a provider.
    """
    if not statement.strip():
        raise ReyLoaderError("load --statement: no statement given.")

    _logger.info("Loading a query on '%s' into %s via '%s'",
                 source_connection, destination, connection)
    total = _load_query_to_table(
        ctx, run_log, statement, source_connection, destination, connection,
        create_destination=create_destination, transform=transform,
    )
    _logger.info("Load complete: %d row(s) loaded.", total)
    return total


def run_load_query_to_file(
    ctx: Namespace,
    run_log,
    statement: str,
    source_connection: str,
    out_file: str,
    *,
    transform: Any = None,
) -> int:
    """Load what one statement returns into one file.

    The same wrapper as ``run_load_query`` with the other end swapped: it logs
    what is being loaded and where, calls the library, and logs the count.

    ONE CONNECTION, AND IT IS THE SOURCE'S. A file destination has none, so
    none is taken -- accepting one and ignoring it would leave an operator
    believing the rows had gone to a database.

    NO FILE TYPE. The destination's format comes from ``out_file``'s own
    suffix, through the resolver every file source already goes through.
    ``--file-type`` describes a data file being READ and is refused beside a
    statement, so there is nothing here for it to mean.

    Parameters
    ----------
    statement : str
        The SQL whose result is written. Passed as written.
    source_connection : str
        Name of the configured connection the statement runs on.
    out_file : str
        Where the rows go. Its suffix names the format.
    transform : Any
        A transform declaration. Absent means the rows are written as the
        query returned them.

    Returns
    -------
    int
        Rows written.

    Raises
    ------
    ReyLoaderError
        If the statement is empty, for the reason ``run_load_query`` gives.
    """
    if not statement.strip():
        raise ReyLoaderError("load --statement: no statement given.")

    _logger.info("Loading a query on '%s' into %s",
                 source_connection, out_file)
    total = _load_query_to_file(
        ctx, run_log, statement, source_connection, out_file,
        transform=transform,
    )
    _logger.info("Load complete: %d row(s) written.", total)
    return total


def run_load_one(ctx: Namespace, run_log, data_source_name: str,
                 file_path: Path) -> int:
    """Load exactly one named file, skipping discovery.

    ``run_load`` scans every configured data source for files matching its
    pickup pattern. This loads the file it is given, which is what an operator
    re-running a single delivery actually wants.

    The data source must be NAMED. It cannot be inferred: the installations
    that configure a loader declare more than one, and inferring it while only
    one existed would become a silent change of meaning the moment a second
    was added.

    Resolution reuses ``workflow``'s own helpers rather than repeating them --
    the workflow already answers "which data source" and "which load", and
    both already fail closed. Two lookups would be one mechanism written
    twice.

    Parameters
    ----------
    ctx : Namespace
        Application context built by build_ctx().
    run_log : Any
        The run's log, recording what this load did.
    data_source_name : str
        Name of the configured data source owning the destination.
    file_path : Path
        The file to load.

    Returns
    -------
    int
        Rows loaded.

    Raises
    ------
    ReyLoaderError
        If no data source was named, or the file does not exist. An unknown
        data source is refused by the shared lookup.
    """
    # Local import: workflow imports this module's run_load, so importing it
    # at module scope would close the cycle.
    from rey_loader.workflow import _data_source, _first_load

    if not data_source_name:
        raise ReyLoaderError(
            "load --file requires --data-source: the data source owning the "
            "destination table cannot be inferred."
        )
    if not file_path.is_file():
        raise ReyLoaderError(f"load --file: no such file: {file_path}")

    data_source = _data_source(ctx, {"data_source": data_source_name})
    load_cfg = _first_load(data_source)

    _logger.info("Loading one file: %s -> data source '%s'",
                 file_path.name, data_source_name)
    total = _load_one(ctx, run_log, data_source, load_cfg, file_path)
    _logger.info("Load complete: %d row(s) loaded.", total)
    return total
