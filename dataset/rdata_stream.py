"""Stream one data frame out of an .RData file, one column at a time.

Builder side only. An .RData file is a compressed XDR stream of R objects
(R Internals, "Serialization formats"). A data frame is a list of columns, each
written as a header, a length and one contiguous block of big-endian doubles or
integers; the frame's attributes (names, row.names, class) follow the columns.
Each column is read in chunks and cast straight to float32, so a float64 copy of
the whole frame never exists. Per-column statistics are kept in float64 so
callers can check id columns without trusting the float32 copy.

Errors name only type codes, column positions and byte offsets, never values.
"""

import bz2
import gzip
import lzma
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# SEXP type codes.
SYMSXP = 1
LISTSXP = 2
LANGSXP = 6
CHARSXP = 9
LGLSXP = 10
INTSXP = 13
REALSXP = 14
CPLXSXP = 15
STRSXP = 16
VECSXP = 19
EXPRSXP = 20
RAWSXP = 24
# Serialization-only codes.
ALTREP_SXP = 238
BASEENV_SXP = 241
EMPTYENV_SXP = 242
BASENAMESPACE_SXP = 247
MISSINGARG_SXP = 251
UNBOUNDVALUE_SXP = 252
GLOBALENV_SXP = 253
NILVALUE_SXP = 254
REFSXP = 255

_NO_PAYLOAD = {
    NILVALUE_SXP, EMPTYENV_SXP, BASEENV_SXP, GLOBALENV_SXP,
    UNBOUNDVALUE_SXP, MISSINGARG_SXP, BASENAMESPACE_SXP,
}
_FIXED_WIDTH = {LGLSXP: 4, INTSXP: 4, REALSXP: 8, CPLXSXP: 16, RAWSXP: 1}

HAS_ATTR = 1 << 9
HAS_TAG = 1 << 10
NA_INTEGER = -(2**31)

# Anything we materialise as a Python object (names, class, ALTREP info) is small.
_MAX_SMALL = 10_000
_SKIP_BYTES = 1 << 20


class RDataError(ValueError):
    pass


@dataclass
class ColumnStats:
    """float64 statistics over one column, taken before the float32 cast."""
    nonfinite: int = 0
    min: float = float("nan")  # over finite values
    max: float = float("nan")
    integral: bool = True  # every finite value is a whole number

    def update(self, values):
        finite = np.isfinite(values)
        n_finite = int(np.count_nonzero(finite))
        self.nonfinite += values.size - n_finite
        if n_finite == 0:
            return
        v = values if n_finite == values.size else values[finite]
        lo, hi = float(v.min()), float(v.max())
        self.min = lo if np.isnan(self.min) else min(self.min, lo)
        self.max = hi if np.isnan(self.max) else max(self.max, hi)
        if self.integral:
            self.integral = bool(np.all(v == np.trunc(v)))


@dataclass
class Frame:
    name: str  # the object's name in the file
    nrows: int
    columns: dict = field(default_factory=dict)  # column name -> float32 array
    stats: dict = field(default_factory=dict)  # column name -> ColumnStats


@dataclass(frozen=True)
class _Symbol:
    name: str


def read_frame(path, *, chunk_values=1 << 20):
    """Read the single data frame saved in an .RData file."""
    with _open(Path(path)) as f:
        return _Parser(f, chunk_values).file()


def _open(path):
    with open(path, "rb") as f:
        head = f.read(6)
    if head[:2] == b"\x1f\x8b":
        return gzip.open(path, "rb")
    if head[:3] == b"BZh":
        return bz2.open(path, "rb")
    if head[:6] == b"\xfd7zXZ\x00":
        return lzma.open(path, "rb")
    return open(path, "rb")


class _Parser:
    def __init__(self, f, chunk_values):
        self._f = f
        self._pos = 0  # bytes consumed from the decompressed stream
        self._chunk = chunk_values
        self._refs = []  # symbols, in the order the writer registered them

    # --- primitive reads ---

    def _fail(self, msg):
        raise RDataError(f"{msg} (byte {self._pos})")

    def _read(self, n):
        buf = self._f.read(n)
        while len(buf) < n:
            more = self._f.read(n - len(buf))
            if not more:
                self._fail("unexpected end of stream")
            buf += more
        self._pos += n
        return buf

    def _int(self):
        return struct.unpack(">i", self._read(4))[0]

    def _skip_bytes(self, n):
        while n > 0:
            k = min(n, _SKIP_BYTES)
            self._read(k)
            n -= k

    def _flags(self):
        flags = self._int()
        return flags & 0xFF, flags

    def _length(self):
        n = self._int()
        if n == -1:
            self._fail("long vectors are not supported")
        if n < 0:
            self._fail("negative vector length")
        return n

    # --- top level ---

    def file(self):
        magic = self._read(5)
        if magic not in (b"RDX2\n", b"RDX3\n"):
            self._fail("not an RData file in format version 2 or 3")
        if self._read(2) != b"X\n":
            self._fail("only the XDR binary format is supported")
        version = self._int()
        self._int()  # writer's R version
        self._int()  # minimum reader version
        if version == 3:
            self._skip_bytes(self._int())  # native encoding name
        elif version != 2:
            self._fail(f"unsupported serialization version {version}")

        t, flags = self._flags()
        if t != LISTSXP or not flags & HAS_TAG:
            self._fail(f"expected a named list of saved objects, found type code {t}")
        if flags & HAS_ATTR:
            self._skip_item()
        tag = self._value_item()
        if not isinstance(tag, _Symbol):
            self._fail("saved object has no name")
        frame = self._frame(tag.name)
        t, _ = self._flags()
        if t != NILVALUE_SXP:
            self._fail("file holds more than one object")
        return frame

    def _frame(self, name):
        t, flags = self._flags()
        if t != VECSXP:
            self._fail(f"saved object is not a data frame (type code {t})")
        arrays, stats = [], []
        for j in range(self._length()):
            arr, st = self._column(j)
            if arrays and arr.size != arrays[0].size:
                self._fail(f"column {j + 1} has a different length from column 1")
            arrays.append(arr)
            stats.append(st)

        names, klass = None, None
        if flags & HAS_ATTR:
            for tag, value in self._attributes(keep={"names", "class"}):
                if tag == "names":
                    names = value
                elif tag == "class":
                    klass = value
        if not klass or "data.frame" not in klass:
            self._fail("saved object is not a data frame (no data.frame class)")
        if names is None or len(names) != len(arrays):
            self._fail("data frame names do not match its column count")
        if len(set(names)) != len(names):
            self._fail("data frame has duplicate column names")

        nrows = arrays[0].size if arrays else 0
        return Frame(name=name, nrows=nrows,
                     columns=dict(zip(names, arrays)), stats=dict(zip(names, stats)))

    def _attributes(self, keep):
        """Walk an attribute pairlist. Materialise only the tags in `keep`."""
        t, flags = self._flags()
        out = []
        while t != NILVALUE_SXP:
            if t != LISTSXP:
                self._fail(f"attribute list has type code {t}")
            if flags & HAS_ATTR:
                self._skip_item()
            tag = self._value_item() if flags & HAS_TAG else None
            tag = tag.name if isinstance(tag, _Symbol) else None
            if tag in keep:
                out.append((tag, self._value_item()))
            else:
                self._skip_item()
            t, flags = self._flags()
        return out

    # --- columns ---

    def _column(self, j):
        t, flags = self._flags()
        if t == ALTREP_SXP:
            return self._altrep_column(j)
        if flags & HAS_ATTR:
            self._fail(f"column {j + 1} carries attributes (type code {t}); "
                       "only plain numeric columns are supported")
        if t == REALSXP:
            return self._numeric(np.dtype(">f8"))
        if t == INTSXP:
            return self._numeric(np.dtype(">i4"))
        self._fail(f"column {j + 1} has unsupported type code {t}")

    def _numeric(self, dtype):
        n = self._length()
        out = np.empty(n, dtype=np.float32)
        stats = ColumnStats()
        pos = 0
        while pos < n:
            k = min(self._chunk, n - pos)
            raw = np.frombuffer(self._read(k * dtype.itemsize), dtype=dtype)
            values = raw.astype(np.float64)
            if dtype.kind == "i":
                values[raw == NA_INTEGER] = np.nan
            stats.update(values)
            out[pos:pos + k] = values
            pos += k
        return out, stats

    def _altrep_column(self, j):
        info = self._value_item()
        try:
            cls = info[0][1].name
        except (TypeError, IndexError, AttributeError):
            self._fail(f"column {j + 1} has an unreadable compact-form header")
        if cls in ("compact_intseq", "compact_realseq"):
            state = self._value_item()
            if state is None or len(state) != 3:
                self._fail(f"column {j + 1} has an unreadable compact sequence")
            n, start, step = int(state[0]), float(state[1]), float(state[2])
            values = start + step * np.arange(n, dtype=np.float64)
            stats = ColumnStats()
            stats.update(values)
            arr = values.astype(np.float32)
        elif cls in ("wrap_real", "wrap_integer"):
            t, flags = self._flags()
            if t != VECSXP or self._length() != 2:
                self._fail(f"column {j + 1} has an unreadable wrapper")
            arr, stats = self._column(j)
            self._skip_item()  # wrapper metadata
            if flags & HAS_ATTR:
                self._skip_item()
        else:
            self._fail(f"column {j + 1} uses an unsupported compact form")
        t, _ = self._flags()  # the column's own attributes
        if t != NILVALUE_SXP:
            self._fail(f"column {j + 1} carries attributes; "
                       "only plain numeric columns are supported")
        return arr, stats

    # --- generic items ---

    def _ref(self, flags):
        idx = flags >> 8
        if idx == 0:
            idx = self._int()
        if not 1 <= idx <= len(self._refs):
            self._fail(f"reference {idx} cannot be resolved")
        return self._refs[idx - 1]

    def _symbol(self):
        t, flags = self._flags()
        if t != CHARSXP:
            self._fail(f"symbol name has type code {t}")
        sym = _Symbol(self._charsxp(flags) or "")
        self._refs.append(sym)
        return sym

    def _charsxp(self, flags):
        n = self._int()
        if n == -1:
            return None  # NA_character_
        raw = self._read(n)
        latin1 = flags & (1 << (12 + 2))  # LATIN1_MASK in the levels field
        return raw.decode("latin-1" if latin1 else "utf-8", errors="replace")

    def _value_item(self):
        """Read one small item into Python objects."""
        t, flags = self._flags()
        if t in _NO_PAYLOAD:
            return None
        if t == REFSXP:
            return self._ref(flags)
        if t == SYMSXP:
            return self._symbol()
        if t == CHARSXP:
            return self._charsxp(flags)
        if t in (LISTSXP, LANGSXP):
            items = []
            while t not in _NO_PAYLOAD:
                if t not in (LISTSXP, LANGSXP):
                    self._fail(f"pairlist tail has type code {t}")
                if flags & HAS_ATTR:
                    self._skip_item()
                tag = self._value_item() if flags & HAS_TAG else None
                items.append((tag, self._value_item()))
                t, flags = self._flags()
            return items
        if t in (STRSXP, VECSXP, EXPRSXP, LGLSXP, INTSXP, REALSXP):
            n = self._length()
            if n > _MAX_SMALL:
                self._fail(f"unexpectedly large object (type code {t})")
            if t == STRSXP:
                value = []
                for _ in range(n):
                    et, eflags = self._flags()
                    if et != CHARSXP:
                        self._fail(f"string element has type code {et}")
                    value.append(self._charsxp(eflags))
            elif t in (VECSXP, EXPRSXP):
                value = [self._value_item() for _ in range(n)]
            elif t == REALSXP:
                value = np.frombuffer(self._read(8 * n), dtype=">f8").astype(np.float64)
            else:
                value = np.frombuffer(self._read(4 * n), dtype=">i4").astype(np.int64)
            if flags & HAS_ATTR:
                self._skip_item()
            return value
        self._fail(f"unsupported type code {t}")

    def _skip_item(self):
        """Consume one item of any size without building per-element objects.
        Symbols are still registered, because later references may point at them."""
        t, flags = self._flags()
        if t in _NO_PAYLOAD:
            return
        if t == REFSXP:
            self._ref(flags)
            return
        if t == SYMSXP:
            self._symbol()
            return
        if t == CHARSXP:
            n = self._int()
            if n > 0:
                self._skip_bytes(n)
            return
        if t in (LISTSXP, LANGSXP):
            while t not in _NO_PAYLOAD:
                if t not in (LISTSXP, LANGSXP):
                    self._fail(f"pairlist tail has type code {t}")
                if flags & HAS_ATTR:
                    self._skip_item()
                if flags & HAS_TAG:
                    self._skip_item()
                self._skip_item()
                t, flags = self._flags()
            return
        if t == ALTREP_SXP:
            self._skip_item()  # class info
            self._skip_item()  # state
            self._skip_item()  # attributes
            return
        if t in _FIXED_WIDTH:
            self._skip_bytes(self._length() * _FIXED_WIDTH[t])
        elif t == STRSXP:
            for _ in range(self._length()):
                _, n = struct.unpack(">ii", self._read(8))
                if n > 0:
                    self._skip_bytes(n)
        elif t in (VECSXP, EXPRSXP):
            for _ in range(self._length()):
                self._skip_item()
        else:
            self._fail(f"unsupported type code {t}")
        if flags & HAS_ATTR:
            self._skip_item()
