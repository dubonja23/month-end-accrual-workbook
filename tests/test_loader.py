"""Loader validation."""
import shutil

import pytest

from accrual_workbook.engine.loader import InputError, load_inputs


def test_missing_columns_are_rejected_and_named(sample_dir, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(sample_dir, bad)
    roster = (bad / "roster.csv").read_text(encoding="utf-8").splitlines()
    header = roster[0].split(",")
    keep = [i for i, c in enumerate(header) if c not in ("owner", "gl_account")]
    lines = [",".join(row.split(",")[i] for i in keep) for row in roster]  # roster has no quoted commas
    (bad / "roster.csv").write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(InputError) as err:
        load_inputs(bad)
    assert "roster.csv" in str(err.value)
    assert "gl_account" in str(err.value) and "owner" in str(err.value)


def test_missing_file_is_reported(sample_dir, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(sample_dir, bad)
    (bad / "je_dims.csv").unlink()
    with pytest.raises(InputError, match="je_dims.csv"):
        load_inputs(bad)
