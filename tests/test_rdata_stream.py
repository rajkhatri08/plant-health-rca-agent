"""The streamed RData reader, on synthetic files only."""

import numpy as np
import pandas as pd
import pyreadr
import pytest

from dataset.rdata_stream import RDataError, read_frame
from tests.rdata_writer import compress, rdata_bytes, write_rdata

COMPRESSIONS = ["gzip", "bzip2", "xz", "none"]


def _columns(n=10, seed=0):
    rng = np.random.default_rng(seed)
    return {
        "faultNumber": np.full(n, 3.0),
        "simulationRun": np.repeat([1.0, 2.0], n // 2),
        "sample": np.tile(np.arange(1.0, n // 2 + 1), 2),
        "xmeas_1": rng.normal(50.0, 5.0, n),
        "xmv_1": rng.normal(20.0, 1.0, n),
    }


def _assert_matches_pyreadr(path, name):
    ours = read_frame(path, chunk_values=3)
    ref = pyreadr.read_r(str(path))[name]
    assert ours.name == name
    assert list(ours.columns) == list(ref.columns)
    assert ours.nrows == len(ref)
    for col in ref.columns:
        expected = ref[col].to_numpy(dtype=np.float64).astype(np.float32)
        np.testing.assert_array_equal(ours.columns[col], expected)
        assert ours.columns[col].dtype == np.float32


@pytest.mark.parametrize("compression", COMPRESSIONS)
def test_matches_pyreadr_on_our_writer(tmp_path, compression):
    path = write_rdata(tmp_path / "x.RData", "frame_a", _columns(), compression=compression)
    _assert_matches_pyreadr(path, "frame_a")


@pytest.mark.parametrize("compression", COMPRESSIONS)
def test_matches_pyreadr_on_pyreadr_writer(tmp_path, compression):
    path = tmp_path / "x.RData"
    pyreadr.write_rdata(str(path), pd.DataFrame(_columns()), df_name="frame_b")
    if compression != "none":
        path.write_bytes(compress(path.read_bytes(), compression))
    _assert_matches_pyreadr(path, "frame_b")


@pytest.mark.parametrize("chunk", [1, 3, 4, 7, 1000])
def test_chunk_boundaries(tmp_path, chunk):
    cols = _columns(n=14)
    path = write_rdata(tmp_path / "x.RData", "f", cols)
    frame = read_frame(path, chunk_values=chunk)
    for name, values in cols.items():
        np.testing.assert_array_equal(frame.columns[name], values.astype(np.float32))


@pytest.mark.parametrize("row_names", ["compact", "int", "char", "altrep"])
def test_row_names_are_skipped(tmp_path, row_names):
    cols = _columns()
    path = write_rdata(tmp_path / "x.RData", "f", cols, row_names=row_names, extra_attrs=True)
    frame = read_frame(path, chunk_values=4)
    assert list(frame.columns) == list(cols)
    np.testing.assert_array_equal(frame.columns["xmeas_1"], cols["xmeas_1"].astype(np.float32))


def test_integer_columns_and_na(tmp_path):
    cols = {"a": np.array([1, 2, -(2**31), 4]), "b": np.array([1.5, np.nan, np.inf, 2.0])}
    path = write_rdata(tmp_path / "x.RData", "f", cols, kinds={"a": "int"})
    frame = read_frame(path)
    np.testing.assert_array_equal(frame.columns["a"], np.array([1, 2, np.nan, 4], np.float32))
    assert frame.stats["a"].nonfinite == 1
    assert frame.stats["a"].integral and (frame.stats["a"].min, frame.stats["a"].max) == (1, 4)
    assert frame.stats["b"].nonfinite == 2
    assert not frame.stats["b"].integral


def test_stats_use_float64_not_float32(tmp_path):
    # 3.0000000001 rounds to 3.0 in float32, but it is not a whole number.
    path = write_rdata(tmp_path / "x.RData", "f", {"a": np.array([1.0, 3.0000000001])})
    frame = read_frame(path)
    assert frame.columns["a"][1] == np.float32(3.0)
    assert not frame.stats["a"].integral


@pytest.mark.parametrize("kind", ["intseq", "wrap_real"])
def test_altrep_columns(tmp_path, kind):
    cols = {"sample": np.arange(1.0, 9.0), "b": np.arange(8.0) * 0.5}
    path = write_rdata(tmp_path / "x.RData", "f", cols, kinds={"sample": kind})
    frame = read_frame(path, chunk_values=3)
    np.testing.assert_array_equal(frame.columns["sample"], np.arange(1, 9, dtype=np.float32))
    assert frame.stats["sample"].integral


@pytest.mark.parametrize("kind", ["cplx", "factor"])
def test_unsupported_column_stops_without_values(tmp_path, kind):
    cols = {"a": np.array([98765.4321, 98765.4321]), "b": np.array([1.0, 2.0])}
    path = write_rdata(tmp_path / "x.RData", "f", cols, kinds={"b": kind})
    with pytest.raises(RDataError) as err:
        read_frame(path)
    msg = str(err.value)
    assert "column 2" in msg and "byte" in msg
    assert "98765" not in msg and "9.8765" not in msg


def test_truncated_file(tmp_path):
    raw = rdata_bytes("f", _columns())
    path = tmp_path / "x.RData"
    path.write_bytes(raw[:-40])
    with pytest.raises(RDataError, match="unexpected end"):
        read_frame(path)


def test_not_rdata(tmp_path):
    path = tmp_path / "x.RData"
    path.write_bytes(b"PAR1 not an RData file")
    with pytest.raises(RDataError, match="not an RData file"):
        read_frame(path)