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


# c_scan.py's three bracket walkers. Arguments the plain versions treat oddly (a negative offset indexes from the end, an
# offset past the text raises IndexError) go back to them, so every answer and every exception stays theirs.
python_c_close = None
python_enclosing_block = None
python_header_before = None


def c_close(str clean, Py_ssize_t opening, str left=u'{', str right=u'}'):
    """c_scan.close: the index of the bracket closing the one at `opening`, or -1."""
    cdef Py_ssize_t length = len(clean), i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if opening < 0 or len(left) != 1 or len(right) != 1:
        return python_c_close(clean, opening, left, right)
    open_char = left[0]
    close_char = right[0]
    for i in range(opening, length):
        c = clean[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return i
    return -1


def c_enclosing_block(str clean, Py_ssize_t at, Py_ssize_t lo):
    """c_scan.enclosing_block: the `{` of the innermost block around `at` (not before `lo`), or -1."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if lo < 0 or at > len(clean) + 1 or (at == len(clean) + 1 and at - 1 >= lo):
        return python_enclosing_block(clean, at, lo)
    i = at - 1
    while i >= lo:
        c = clean[i]
        if c == u'}':
            depth += 1
        elif c == u'{':
            if depth == 0:
                return i
            depth -= 1
        i -= 1
    return -1


def c_header_before(str clean, Py_ssize_t opening):
    """c_scan.header_before: the statement header just before the `{` at `opening`."""
    cdef Py_ssize_t i = opening - 1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if opening < 0 or opening > len(clean):
        return python_header_before(clean, opening)
    while i >= 0:
        c = clean[i]
        if c == u')':
            depth += 1
        elif c == u'(':
            depth -= 1
        elif depth == 0 and (c == u';' or c == u'{' or c == u'}'):
            break
        i -= 1
    return clean[i + 1:opening].strip()


python_own_loop_statements = None
header_opens_loop = None  # c_scan's regex test of a header: `header_opens_loop(header, word)` (regexes stay Python)


def c_own_loop_statements(str clean, Py_ssize_t lo, Py_ssize_t hi, str word):
    """c_scan.own_loop_statements: offsets of `word` in clean[lo:hi] that belong to the loop whose body is that range."""
    cdef Py_ssize_t i, boundary = lo - 1, depth_paren = 0, loops_open = 0, wordlen = len(word)
    cdef Py_ssize_t length = len(clean)
    cdef Py_UCS4 c, first
    cdef bint opens
    cdef list stack = [], out = []
    if lo < 0 or hi > length or wordlen == 0:
        return python_own_loop_statements(clean, lo, hi, word)
    first = word[0]
    for i in range(lo, hi):
        c = clean[i]
        if c == u'(':
            depth_paren += 1
        elif c == u')':
            depth_paren -= 1
        elif c == u'{' and depth_paren == 0:
            opens = header_opens_loop(clean[boundary + 1:i].strip(), word)
            stack.append(opens)
            if opens:
                loops_open += 1
            boundary = i
        elif c == u'}' and depth_paren == 0:
            if stack:
                if stack.pop():
                    loops_open -= 1
            boundary = i
        elif c == u';' and depth_paren == 0:
            boundary = i
        elif c == first and clean.startswith(word, i):
            if i > 0 and (clean[i - 1].isalnum() or clean[i - 1] == u'_'):
                continue
            if i + wordlen < length and (clean[i + wordlen].isalnum() or clean[i + wordlen] == u'_'):
                continue
            if loops_open == 0:
                out.append(i)
    return out


# The bracket matchers many modules wrote for themselves: two shapes, here once, typed. A module keeps its own loop as
# `_python_<name>` and answers with the kernel when it is built; arguments the loop reads in its own way (a negative start,
# brackets of more than one character, two equal brackets) come back as NotImplemented and go to that twin.

def close_if(str text, Py_ssize_t start, str left, str right, object miss):
    """The index of the bracket closing the one at `start`, the depth tested only after a closing bracket; `miss` if none."""
    cdef Py_ssize_t length = len(text), i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if start < 0 or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    for i in range(start, length):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return i
    return miss


def close_every(str text, Py_ssize_t start, str left, str right, bint past, object miss):
    """The index of the bracket closing the one at `start` (`past`: one past it), the depth tested at every character, so a
    start that is no bracket answers itself; `miss` if none."""
    cdef Py_ssize_t length = len(text), i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if start < 0 or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    for i in range(start, length):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
        if depth == 0:
            return i + 1 if past else i
    return miss


def close_if_past(str text, Py_ssize_t start, str left, str right, object miss):
    """close_if, answering one past the closing bracket."""
    cdef Py_ssize_t length = len(text), i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if start < 0 or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    for i in range(start, length):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return i + 1
    return miss


def enclosing_end(str text, Py_ssize_t start, Py_ssize_t limit, object miss):
    """The `}` that closes the block around `start`, looking no further than `limit` (a `{` at or after `start` opens a
    nested block, which is skipped); `miss` if there is none."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if start < 0 or limit < 0 or limit > len(text):
        return NotImplemented
    for i in range(start, limit):
        c = text[i]
        if c == u'{':
            depth += 1
        elif c == u'}':
            if depth == 0:
                return i
            depth -= 1
    return miss
