"""The SQL file checksum survives the move to rey_lib.encryption.

_checksum feeds execution audit logging: the digest of the SQL that actually
ran. It is recorded, so a changed digest would not fail, it would make old audit
records disagree with new ones for the same file.

One site moved. The expected digest is stated independently here rather than by
calling the function twice, and a differential test reproduces the exact
pre-migration expression.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rey_loader.sql_apply import _checksum

# SQL files are text in practice, but the digest was always over raw bytes.
SAMPLES = (
    b"",
    b"SELECT 1;\n",
    "SELECT 'café' FROM t;\n".encode("utf-8"),
    "-- 字段\nSELECT 1;\n".encode("utf-8"),
    b"SELECT 1;\r\nSELECT 2;\r\n",
    b"\xff\xfe not valid utf-8",
    b"x" * 2_000_000,
)


@pytest.mark.parametrize("payload", SAMPLES)
def test_the_checksum_is_unchanged(tmp_path: Path, payload: bytes) -> None:
    """Stated independently: the digest of the file's bytes."""
    sql_file = tmp_path / "step.sql"
    sql_file.write_bytes(payload)

    assert _checksum(sql_file) == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("payload", SAMPLES)
def test_the_checksum_matches_the_previous_expression(
    tmp_path: Path, payload: bytes
) -> None:
    """The pre-migration expression, reproduced verbatim."""
    sql_file = tmp_path / "step.sql"
    sql_file.write_bytes(payload)

    previous = hashlib.sha256(sql_file.read_bytes()).hexdigest()

    assert _checksum(sql_file) == previous


def test_bytes_are_hashed_as_stored_without_newline_translation(
    tmp_path: Path,
) -> None:
    """A CRLF SQL file must not depend on the platform that read it."""
    sql_file = tmp_path / "crlf.sql"
    sql_file.write_bytes(b"SELECT 1;\r\n")

    assert _checksum(sql_file) == hashlib.sha256(b"SELECT 1;\r\n").hexdigest()
    assert _checksum(sql_file) != hashlib.sha256(b"SELECT 1;\n").hexdigest()


def test_a_missing_sql_file_still_raises(tmp_path: Path) -> None:
    """read_bytes raised OSError and so does the primitive.

    A caller that relied on the failure keeps getting one; returning a digest
    for a file that is not there would be a false audit record.
    """
    with pytest.raises(OSError):
        _checksum(tmp_path / "absent.sql")


def test_no_rey_loader_module_computes_a_plain_sha256_itself() -> None:
    """Drift guard.

    Narrow on purpose. It flags direct plain SHA-256 use only. A
    configuration-driven hashlib.new(algorithm) call is an agreed exclusion --
    the algorithm is chosen by configuration there, so forcing it onto a
    SHA-256 primitive would remove a configured capability. rey_loader has no
    such site today; the exclusion is written in so that adding one legitimately
    does not trip this test.
    """
    package_root = Path(__file__).resolve().parent.parent / "rey_loader"
    offenders = []
    for path in sorted(package_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        direct = [
            line.strip()
            for line in source.splitlines()
            if "hashlib.sha256" in line or "hashlib.md5" in line
        ]
        if direct:
            offenders.append((path.name, direct))

    assert offenders == []
