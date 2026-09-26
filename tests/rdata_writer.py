"""Test-only writer for R's XDR serialization (format version 3).

Produces what an R `save()` of a data frame produces, including forms pyreadr
can't write: full-length integer or character row.names, ALTREP compact
sequences and wrappers, repeated symbols written as references, and column
types the reader must reject.
"""

import bz2
import gzip
import lzma
import struct

import numpy as np

NA_INTEGER = -(2**31)


def _i(v):
    return struct.pack(">i", v)


def _flags(t, *, obj=False, attr=False, tag=False, levels=0):
    return _i(t | (obj << 8) | (attr << 9) | (tag << 10) | (levels << 12))


class _Writer:
    def __init__(self):
        self.syms = {}

    def charsxp(self, s):
        if s is None:
            return _flags(9) + _i(-1)
        b = s.encode()
        return _flags(9, levels=64) + _i(len(b)) + b

    def sym(self, name):
        if name in self.syms:
            return _i((self.syms[name] << 8) | 255)
        self.syms[name] = len(self.syms) + 1
        return _flags(1) + self.charsxp(name)

    def strsxp(self, values):
        return _flags(16) + _i(len(values)) + b"".join(self.charsxp(v) for v in values)

    def intsxp(self, values):
        a = np.asarray(values, dtype=">i4")
        return _flags(13) + _i(a.size) + a.tobytes()

    def realsxp(self, values):
        a = np.asarray(values, dtype=">f8")
        return _flags(14) + _i(a.size) + a.tobytes()

    def pairlist(self, items):
        """items: list of (tag or None, encoded value or a callable that encodes it).
        Callables run in stream order, so symbol references stay valid."""
        out = b""
        for tag, value in items:
            out += _flags(2, tag=tag is not None)
            if tag is not None:
                out += self.sym(tag)
            out += value() if callable(value) else value
        return out + _i(254)

    def altrep(self, cls, type_code, state):
        info = self.pairlist([(None, lambda: self.sym(cls)), (None, lambda: self.sym("base")),
                              (None, self.intsxp([type_code]))])
        return _i(238) + info + state() + _i(254)

    def column(self, kind, values):
        if kind == "real":
            return self.realsxp(values)
        if kind == "int":
            return self.intsxp(values)
        if kind == "intseq":  # values must be start, start+1, ...
            n, start = len(values), float(values[0])
            return self.altrep("compact_intseq", 13, lambda: self.realsxp([n, start, 1.0]))
        if kind == "wrap_real":
            return self.altrep("wrap_real", 14, lambda: _flags(19) + _i(2)
                               + self.realsxp(values) + self.intsxp([0, 0]))
        if kind == "cplx":  # unsupported column type
            a = np.zeros(2 * len(values), dtype=">f8")
            return _flags(15) + _i(len(values)) + a.tobytes()
        if kind == "factor":  # an integer column with attributes
            codes = _flags(13, obj=True, attr=True) + _i(len(values))
            codes += np.ones(len(values), dtype=">i4").tobytes()
            return codes + self.pairlist([("levels", lambda: self.strsxp(["a"])),
                                          ("class", lambda: self.strsxp(["factor"]))])
        raise ValueError(kind)

    def row_names(self, kind, n):
        if kind == "compact":
            return self.intsxp([NA_INTEGER, -n])
        if kind == "int":
            return self.intsxp(np.arange(1, n + 1))
        if kind == "char":
            return self.strsxp([str(i) for i in range(1, n + 1)])
        if kind == "altrep":
            return self.altrep("compact_intseq", 13, lambda: self.realsxp([n, 1.0, 1.0]))
        raise ValueError(kind)


def rdata_bytes(name, columns, *, kinds=None, row_names="compact", extra_attrs=False):
    """columns: dict of column name -> 1-D array. kinds: column name -> writer kind
    (default "real")."""
    kinds = kinds or {}
    w = _Writer()
    n = len(next(iter(columns.values()))) if columns else 0
    body = _flags(19, obj=True, attr=True) + _i(len(columns))
    for col, values in columns.items():
        body += w.column(kinds.get(col, "real"), values)
    attrs = [("names", lambda: w.strsxp(list(columns))),
             ("row.names", lambda: w.row_names(row_names, n)),
             ("class", lambda: w.strsxp(["data.frame"]))]
    if extra_attrs:
        attrs.insert(1, ("comment", lambda: w.strsxp(["x"] * 3)))
        attrs.append(("names_again", lambda: w.sym("names")))  # a reference to an earlier symbol
    body += w.pairlist(attrs)

    header = b"RDX3\nX\n" + _i(3) + _i(0x040400) + _i(0x030500) + _i(5) + b"UTF-8"
    return header + _flags(2, tag=True) + w.sym(name) + body + _i(254)


def compress(raw, how):
    if how == "gzip":
        return gzip.compress(raw)
    if how == "bzip2":
        return bz2.compress(raw)
    if how == "xz":
        return lzma.compress(raw)
    if how == "none":
        return raw
    raise ValueError(how)


def write_rdata(path, name, columns, *, compression="gzip", **kwargs):
    path.write_bytes(compress(rdata_bytes(name, columns, **kwargs), compression))
    return path