# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Typed kernels for the scans nearly every family does: C integers over the string's own characters, no regex and no
Match object per bracket. Each answers exactly what its pure-Python twin in the module that imports it answers
(tests/test_scan_kernels.py compares them on random text); the twins stay as the fallback when this isn't built
(scripts: `native_build.py` builds every `.pyx` beside the compiled modules)."""


python_close = None  # pattern_repairs sets its plain scan here: what the typed one doesn't take goes to it


def close(str text, Py_ssize_t start, str left=u'(', str right=u')'):
    """The position just past the bracket that closes the one at `start`: pattern_repairs.close, typed. A negative
    `start` or brackets longer than one character (which the plain scan reads as a character set) are left to it."""
    cdef Py_ssize_t length = len(text), pos
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, ch
    if start < 0 or len(left) != 1 or len(right) != 1:
        return python_close(text, start, left, right)
    open_char = left[0]
    close_char = right[0]
    if open_char == close_char:  # (no caller does this: keep what the plain scan answered)
        return start + 1 if start < length else None
    if start >= length:
        return None
    ch = text[start]
    if ch != open_char and ch != close_char:
        return start + 1
    pos = start
    while pos < length:
        ch = text[pos]
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
        else:
            pos += 1
            continue
        if depth == 0:  # either bracket can bring the depth back to zero (the scan may start on a closer)
            return pos + 1
        pos += 1
    return None
