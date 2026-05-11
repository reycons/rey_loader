"""Shared pytest fixtures for rey_loader tests."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest

from rey_lib.config.config_utils import Namespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ns(data: dict | None = None, **kwargs) -> Namespace:
    """
    Wrap a dict (or keyword arguments) as a rey_lib Namespace.

    Accepts either form:
        _ns({"name": "advantage", "version": "v01"})
        _ns(name="advantage", version="v01")

    The dict form is used when keys contain non-identifier characters
    (e.g. CSV column names with spaces). The kwargs form is cleaner for
    plain identifier keys.
    """
    return Namespace(data if data is not None else kwargs)


def _make_paths(tmp_path: Path) -> Namespace:
    """Create all pipeline directories under tmp_path and return a paths Namespace."""
    dirs = {
        "inbox_path":      tmp_path / "inbox",
        "processing_path": tmp_path / "processing",
        "converted_path":  tmp_path / "converted",
        "loaded_path":     tmp_path / "loaded",
        "rejected_path":   tmp_path / "rejected",
        "archive_path":    tmp_path / "archive",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    # Namespace wraps each Path via _wrap_config_value, which passes
    # non-dict/non-list values through unchanged.
    return _ns(dirs)


# ---------------------------------------------------------------------------
# Core ctx fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctx(tmp_path: Path) -> Namespace:
    """
    Minimal application context for transform-stage tests.

    sql_configs and app_hooks are empty — no hook bindings fire, so no SQL
    Server connection is needed by default. Tests that exercise hooks add
    bindings explicitly (see TestRunTransformWithHooks in test_transform.py).
    batch_id is pre-set to a known value so _build_constants can resolve it.
    """
    # Suppress noisy logging during tests — only WARNING and above shows.
    logging.getLogger("rey_lib").setLevel(logging.WARNING)
    logging.getLogger("rey_loader").setLevel(logging.WARNING)

    paths = _make_paths(tmp_path)
    data_source = _make_advantage_data_source(paths)

    return _ns({
        "env":              "dev",
        "log_depth":        0,
        "log_file":         str(tmp_path / "test.log"),
        "cli_call":         "pytest",                 # stand-in for sys.argv
        "batch_id":         None,
        "batch_start_dt":   datetime(2026, 5, 8, 9, 0, 0),
        "sql_configs":      [],
        "app_hooks":        [],                       # run-level bindings; populated by tests as needed
        "data_sources":     [data_source],
    })


# ---------------------------------------------------------------------------
# Data source fixtures
# ---------------------------------------------------------------------------

def _make_advantage_data_source(paths: Namespace) -> Namespace:
    """
    Build a minimal Advantage data source Namespace matching the YAML config.

    Uses the same structure that build_ctx() produces after loading
    data_source.advantage.trade.yaml.
    """
    transform_cfg = _make_advantage_transform_cfg(paths)

    return _ns(
        name="advantage",
        max_files_per_run=10,
        paths=paths,
        transforms=transform_cfg,
        transform_hooks=[],  # transform-level hook bindings; tests add as needed
        loads=[],            # load stage tested separately
    )


def _make_advantage_transform_cfg(paths: Namespace) -> Namespace:
    """Build the v01 advantage_transactions transform Namespace."""
    return _ns(
        name="advantage_transactions",
        version="v01",
        file_type="CSV",
        encoding="utf-8-sig",
        date_format="yyyymmdd",
        file_pattern="tran_{yyyymmdd}.csv",
        header=(
            "TRADE DATE,OFFICE,ACCOUNT,A/C TYPE,BUY/SELL,QTY,EXCH ID,CONTRACT NAME,"
            "YYYY/MM,PROMPT DATE,STRIKE PRICE,PUT/CALL,PRINTABLE PRICE,TRADE TYPE,"
            "CARD/ORDER #,CURRENCY CODE,STYPE,FUTURES CODE,SUB CUSIP,CUSIP,GMI FIRM #,"
            "SALESCODE #,COMMENT CODE,GIVE IN/OUT,GIVE IN FIRM,TRADE PRICE,SPREAD,"
            "OPEN/CLOSE,EXECUTING BROKER,OPPOSITE BROKER,OPPOSITE FIRM,COMMISSION,"
            "COMM A/C TYPE,FEE 1 (CLEARING),FEE 1 A/C TYPE,FEE 2 (EXCHANGE),"
            "FEE 2 A/C TYPE,FEE 3 (NFA),FEE 3 A/C TYPE,BROKERAGE CHARGE,BKG A/C TYPE,"
            "GIVE IN CHARGE,G/I A/C TYPE,OTHER CHARGE,OTHER A/C TYPE,WIRE CHARGE,"
            "WIRE A/C TYPE,ENTRY DATE,DELETE CODE,GMI TRACER #,JOURNAL SEQUENCE,"
            "ROUND TURN/HALF TURN,DESCRIPTION,JOURNAL RECORD,SUB ACCOUNT,"
            "COMMENT F CODE,MISC.,2 DIGIT EXCHANGE,FUTURE/OPTION,MULTIPLIER,"
            "CLOSE PRICE,XTP ACCOUNT"
        ),
        row_filter=[],
        output=_ns(
            output_dest="converted_path",
            version="v01",
            file=_ns(name="{base_file_name}_{version}.csv"),
        ),
        movements=_ns(
            success=[_ns(move=_ns(**{"from": "inbox_path", "to": "processing_path"}))],
            failure=[_ns(move=_ns(**{"from": "inbox_path", "to": "rejected_path"}))],
        ),
        constants=_ns(
            broker="advantage",
            record_source="CSV Import",
            transform_version="v01",
            source_file="{incoming_file_name}",
            archive_file="{archive_path}",
        ),
        columns=_ns(**{
            "trade_date":           "TRADE DATE",
            "office":               "OFFICE",
            "account":              "ACCOUNT",
            "ac_type":              "A/C TYPE",
            "buy_sell":             "BUY/SELL",
            "qty":                  "QTY",
            "exch_id":              "EXCH ID",
            "contract_name":        "CONTRACT NAME",
            "yyyy_mm":              "YYYY/MM",
            "prompt_date":          "PROMPT DATE",
            "strike_price":         "STRIKE PRICE",
            "put_call":             "PUT/CALL",
            "printable_price":      "PRINTABLE PRICE",
            "trade_type":           "TRADE TYPE",
            "card_order_no":        "CARD/ORDER #",
            "currency_code":        "CURRENCY CODE",
            "stype":                "STYPE",
            "futures_code":         "FUTURES CODE",
            "sub_cusip":            "SUB CUSIP",
            "cusip":                "CUSIP",
            "gmi_firm_no":          "GMI FIRM #",
            "salescode_no":         "SALESCODE #",
            "comment_code":         "COMMENT CODE",
            "give_in_out":          "GIVE IN/OUT",
            "give_in_firm":         "GIVE IN FIRM",
            "trade_price":          "TRADE PRICE",
            "spread":               "SPREAD",
            "open_close":           "OPEN/CLOSE",
            "executing_broker":     "EXECUTING BROKER",
            "opposite_broker":      "OPPOSITE BROKER",
            "opposite_firm":        "OPPOSITE FIRM",
            "commission":           "COMMISSION",
            "comm_ac_type":         "COMM A/C TYPE",
            "fee_1_clearing":       "FEE 1 (CLEARING)",
            "fee_1_ac_type":        "FEE 1 A/C TYPE",
            "fee_2_exchange":       "FEE 2 (EXCHANGE)",
            "fee_2_ac_type":        "FEE 2 A/C TYPE",
            "fee_3_nfa":            "FEE 3 (NFA)",
            "fee_3_ac_type":        "FEE 3 A/C TYPE",
            "brokerage_charge":     "BROKERAGE CHARGE",
            "bkg_ac_type":          "BKG A/C TYPE",
            "give_in_charge":       "GIVE IN CHARGE",
            "gi_ac_type":           "G/I A/C TYPE",
            "other_charge":         "OTHER CHARGE",
            "other_ac_type":        "OTHER A/C TYPE",
            "wire_charge":          "WIRE CHARGE",
            "wire_ac_type":         "WIRE A/C TYPE",
            "entry_date":           "ENTRY DATE",
            "delete_code":          "DELETE CODE",
            "gmi_tracer_no":        "GMI TRACER #",
            "journal_sequence":     "JOURNAL SEQUENCE",
            "round_turn_half_turn": "ROUND TURN/HALF TURN",
            "description":          "DESCRIPTION",
            "journal_record":       "JOURNAL RECORD",
            "sub_account":          "SUB ACCOUNT",
            "comment_f_code":       "COMMENT F CODE",
            "misc":                 "MISC.",
            "two_digit_exchange":   "2 DIGIT EXCHANGE",
            "future_option":        "FUTURE/OPTION",
            "multiplier":           "MULTIPLIER",
            "close_price":          "CLOSE PRICE",
            "xtp_account":          "XTP ACCOUNT",
        }),
        field_transforms=_ns(**{
            "trade_date":      _ns(type="date",    format="%Y%m%d"),
            "prompt_date":     _ns(type="date",    format="%Y%m%d", allow_blank=True),
            "entry_date":      _ns(type="date",    format="%Y-%m-%d"),
            "qty":             _ns(type="numeric", strip_chars=","),
            "strike_price":    _ns(type="numeric", allow_blank=True),
            "printable_price": _ns(type="numeric"),
            "trade_price":     _ns(type="numeric"),
            "commission":      _ns(type="numeric"),
            "fee_1_clearing":  _ns(type="numeric"),
            "fee_2_exchange":  _ns(type="numeric"),
            "fee_3_nfa":       _ns(type="numeric"),
            "brokerage_charge":_ns(type="numeric"),
            "give_in_charge":  _ns(type="numeric"),
            "other_charge":    _ns(type="numeric"),
            "wire_charge":     _ns(type="numeric"),
            "multiplier":      _ns(type="numeric"),
            "close_price":     _ns(type="numeric"),
        }),
    )


# ---------------------------------------------------------------------------
# CSV sample data helpers
# ---------------------------------------------------------------------------

# Canonical header matching the transform config exactly.
ADVANTAGE_HEADER = (
    "TRADE DATE,OFFICE,ACCOUNT,A/C TYPE,BUY/SELL,QTY,EXCH ID,CONTRACT NAME,"
    "YYYY/MM,PROMPT DATE,STRIKE PRICE,PUT/CALL,PRINTABLE PRICE,TRADE TYPE,"
    "CARD/ORDER #,CURRENCY CODE,STYPE,FUTURES CODE,SUB CUSIP,CUSIP,GMI FIRM #,"
    "SALESCODE #,COMMENT CODE,GIVE IN/OUT,GIVE IN FIRM,TRADE PRICE,SPREAD,"
    "OPEN/CLOSE,EXECUTING BROKER,OPPOSITE BROKER,OPPOSITE FIRM,COMMISSION,"
    "COMM A/C TYPE,FEE 1 (CLEARING),FEE 1 A/C TYPE,FEE 2 (EXCHANGE),"
    "FEE 2 A/C TYPE,FEE 3 (NFA),FEE 3 A/C TYPE,BROKERAGE CHARGE,BKG A/C TYPE,"
    "GIVE IN CHARGE,G/I A/C TYPE,OTHER CHARGE,OTHER A/C TYPE,WIRE CHARGE,"
    "WIRE A/C TYPE,ENTRY DATE,DELETE CODE,GMI TRACER #,JOURNAL SEQUENCE,"
    "ROUND TURN/HALF TURN,DESCRIPTION,JOURNAL RECORD,SUB ACCOUNT,"
    "COMMENT F CODE,MISC.,2 DIGIT EXCHANGE,FUTURE/OPTION,MULTIPLIER,"
    "CLOSE PRICE,XTP ACCOUNT"
)

# One valid data row — numeric fields use their typical format, blanks for optional cols.
ADVANTAGE_ROW_VALID = (
    "20260501,001,ACC123,MRG,BUY,10,CBT,SOYBEANS,"
    "202607,20260701,,,"              # YYYY/MM  PROMPT DATE  STRIKE PRICE  PUT/CALL
    "1050.00,RT,"                     # PRINTABLE PRICE  TRADE TYPE
    "ORD-001,USD,,"                   # CARD/ORDER #  CURRENCY CODE  STYPE
    "SB,,,GMI-001,"                   # FUTURES CODE  SUB CUSIP  CUSIP  GMI FIRM #
    "SC-01,,,"                        # SALESCODE #  COMMENT CODE  GIVE IN/OUT
    ",1050.00,,"                      # GIVE IN FIRM  TRADE PRICE  SPREAD
    "O,BRK-A,,,"                      # OPEN/CLOSE  EXECUTING BROKER  OPPOSITE BROKER  OPPOSITE FIRM
    "12.50,MRG,"                      # COMMISSION  COMM A/C TYPE
    "1.25,MRG,"                       # FEE 1 (CLEARING)  FEE 1 A/C TYPE
    "0.50,MRG,"                       # FEE 2 (EXCHANGE)  FEE 2 A/C TYPE
    "0.25,MRG,"                       # FEE 3 (NFA)  FEE 3 A/C TYPE
    "0.00,MRG,"                       # BROKERAGE CHARGE  BKG A/C TYPE
    "0.00,MRG,"                       # GIVE IN CHARGE  G/I A/C TYPE
    "0.00,MRG,"                       # OTHER CHARGE  OTHER A/C TYPE
    "0.00,MRG,"                       # WIRE CHARGE  WIRE A/C TYPE
    "2026-05-01,,"                    # ENTRY DATE  DELETE CODE
    "GMI-TRC-001,1,"                  # GMI TRACER #  JOURNAL SEQUENCE
    "RT,"                             # ROUND TURN/HALF TURN
    "SOYBEANS JUL 26,JNL-001,,"      # DESCRIPTION  JOURNAL RECORD  SUB ACCOUNT
    ",,CB,F,"                         # COMMENT F CODE  MISC.  2 DIGIT EXCHANGE  FUTURE/OPTION
    "5000.00,"                        # MULTIPLIER
    "1048.75,"                        # CLOSE PRICE
    "XTP-ACC-123"                     # XTP ACCOUNT
)


def write_advantage_csv(directory: Path, filename: str, rows: list[str] | None = None) -> Path:
    """
    Write a minimal Advantage trade CSV into directory.

    Parameters
    ----------
    directory : Path
        Destination folder — must already exist.
    filename : str
        File name, e.g. 'tran_20260501.csv'.
    rows : list[str] | None
        Data rows to write after the header. Defaults to one valid row.

    Returns
    -------
    Path
        Full path to the written file.
    """
    if rows is None:
        rows = [ADVANTAGE_ROW_VALID]

    file_path = directory / filename
    lines = [ADVANTAGE_HEADER] + rows
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return file_path
