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


# Scans that run backwards, from a closing bracket or a position to the bracket that opens its block.

def open_if(str text, Py_ssize_t closing, str left, str right, object miss):
    """The index of the bracket opening the one closed at `closing`, the depth tested only after an opener; `miss` if none."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if closing >= len(text) or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    i = closing
    while i >= 0:
        c = text[i]
        if c == close_char:
            depth += 1
        elif c == open_char:
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return miss


def open_every(str text, Py_ssize_t closing, str left, str right, object miss):
    """open_if, the depth tested at every character (so a `closing` that is no bracket answers itself)."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if closing >= len(text) or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    i = closing
    while i >= 0:
        c = text[i]
        if c == close_char:
            depth += 1
        elif c == open_char:
            depth -= 1
        if depth == 0:
            return i
        i -= 1
    return miss


def enclosing_open(str text, Py_ssize_t at, Py_ssize_t low, object miss):
    """The `{` of the innermost block around `at`, looking back from `at - 1` to `low` (inclusive); `miss` if none."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if low < 0 or at - 1 >= len(text):
        return NotImplemented
    i = at - 1
    while i >= low:
        c = text[i]
        if c == u'}':
            depth += 1
        elif c == u'{':
            if depth == 0:
                return i
            depth -= 1
        i -= 1
    return miss


# Statement and list scans: the end of a statement, the brace depth at each position, top-level splits and boundaries.

def statement_end(str text, Py_ssize_t start, Py_ssize_t limit, str opens, str closes, bint past, bint stop_negative,
                  object miss):
    """The `;` at bracket depth 0 that ends the statement starting at `start` (one past it when `past`), looking before
    `limit`; with `stop_negative`, `miss` as soon as a closer has no opener; else `miss`. At most three opening and three
    closing characters (the set is compared as C integers)."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef long o0 = -1, o1 = -1, o2 = -1, c0 = -1, c1 = -1, c2 = -1, ci
    cdef Py_UCS4 c
    if start < 0 or limit < 0 or limit > len(text) or len(opens) > 3 or len(closes) > 3:
        return NotImplemented
    if len(opens) > 0:
        o0 = <long>opens[0]
    if len(opens) > 1:
        o1 = <long>opens[1]
    if len(opens) > 2:
        o2 = <long>opens[2]
    if len(closes) > 0:
        c0 = <long>closes[0]
    if len(closes) > 1:
        c1 = <long>closes[1]
    if len(closes) > 2:
        c2 = <long>closes[2]
    for i in range(start, limit):
        c = text[i]
        ci = <long>c
        if ci == o0 or ci == o1 or ci == o2:
            depth += 1
        elif ci == c0 or ci == c1 or ci == c2:
            depth -= 1
            if stop_negative and depth < 0:
                return miss
        elif c == u';' and depth == 0:
            return i + 1 if past else i
    return miss


def brace_depths(str text, Py_ssize_t start, Py_ssize_t end):
    """The brace depth after each character of text[start:end], as a list."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list flat = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'{':
            depth += 1
        elif c == u'}':
            depth -= 1
        flat.append(depth)
    return flat


def top_split(str text, Py_ssize_t begin, Py_ssize_t end, str separator):
    """The offsets of the top-level `separator` in text[begin:end] (brackets `([{` balanced)."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, sep
    cdef list found = []
    if begin < 0 or end > len(text) or len(separator) != 1:
        return NotImplemented
    sep = separator[0]
    for i in range(begin, end):
        c = text[i]
        if c == u'(' or c == u'[' or c == u'{':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
        if depth == 0 and c == sep:
            found.append(i)
    return found


def boundaries(str text):
    """The offsets just after each top-level `;` (parentheses and brackets balanced), past any spaces and tabs."""
    cdef Py_ssize_t i, end, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list ends = []
    for i in range(length):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        if c == u';' and depth == 0:
            end = i + 1
            while end < length and (text[end] == u' ' or text[end] == u'\t'):
                end += 1
            ends.append(end)
    return ends


def last_statement_start(str text, Py_ssize_t at, Py_ssize_t opening):
    """The offset after the last `;`, `{` or `}` at parenthesis depth 0 between `opening` and `at`."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_ssize_t start = opening + 1
    cdef Py_UCS4 c
    if opening + 1 < 0 or at > len(text):
        return NotImplemented
    for i in range(opening + 1, at):
        c = text[i]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
        if depth == 0 and (c == u';' or c == u'{' or c == u'}'):
            start = i + 1
    return start


def split_statements(str text, Py_ssize_t lo, Py_ssize_t hi):
    """[(start, end)] of the `;`-terminated statements of text[lo:hi], leading whitespace left out of each start."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_ssize_t at = lo
    cdef Py_UCS4 c
    cdef list out = []
    if lo < 0 or hi > len(text):
        return NotImplemented
    for i in range(lo, hi):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        if c == u';' and depth == 0:
            while at < i and text[at].isspace():
                at += 1
            out.append((at, i + 1))
            at = i + 1
    return out


def segments(str text, Py_ssize_t start, Py_ssize_t end):
    """[(begin, stop, terminator)] of the text between `;`, `{` and `}` at parenthesis depth 0 (begin past leading space)."""
    cdef Py_ssize_t i, begin = start, lead
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list found = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif depth == 0 and (c == u';' or c == u'{' or c == u'}'):
            lead = begin
            while lead < i and text[lead].isspace():
                lead += 1
            found.append((lead, i, text[i]))
            begin = i + 1
    return found


# More list-returning scans: call arguments, top-level flags and statements, and splits at a top-level token.

def argument_spans(str text, Py_ssize_t start, Py_ssize_t end):
    """[(begin, end)] of the top-level comma-separated arguments of text[start:end] (brackets `([{` balanced); the last
    one only when it is not blank."""
    cdef Py_ssize_t i, begin = start
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list spans = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'(' or c == u'[' or c == u'{':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
        if c == u',' and depth == 0:
            spans.append((begin, i))
            begin = i + 1
    if text[begin:end].strip():
        spans.append((begin, end))
    return spans


def top_level_flags(str text, Py_ssize_t start):
    """For each offset of text[start:]: whether it lies outside every bracket (`([{`), as a list of bools."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list flags = []
    if start < 0:
        return NotImplemented
    for i in range(start, len(text)):
        c = text[i]
        if c == u'(' or c == u'[' or c == u'{':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
        flags.append(depth == 0)
    return flags


def top_statements(str text, Py_ssize_t lo, Py_ssize_t hi):
    """[(start, end)] of the `;`-terminated statements of text[lo:hi] at its own level (nested blocks skipped)."""
    cdef Py_ssize_t i, begin = lo
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list out = []
    if lo < 0 or hi > len(text):
        return NotImplemented
    for i in range(lo, hi):
        c = text[i]
        if c == u'{':
            depth += 1
        elif c == u'}':
            depth -= 1
            if depth == 0:
                begin = i + 1
        elif c == u';' and depth == 0:
            out.append((begin, i + 1))
            begin = i + 1
    return out


def split_top(str text, str token, bint square):
    """`text` cut at each `token` outside parentheses (and brackets, when `square`)."""
    cdef Py_ssize_t at = 0, last = 0, length = len(text), token_length = len(token)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, first
    cdef list parts = []
    if token_length == 0:
        return NotImplemented
    first = token[0]
    while at < length:
        c = text[at]
        if c == u'(' or (square and c == u'['):
            depth += 1
        elif c == u')' or (square and c == u']'):
            depth -= 1
        if depth == 0 and c == first and text.startswith(token, at):
            parts.append(text[last:at])
            at += token_length
            last = at
            continue
        at += 1
    parts.append(text[last:])
    return parts


# More shapes: mixed-bracket statements, depth tables, `&&` operands, a statement's start looking back, a net brace depth, the next argument.

def statements_mixed(str text, Py_ssize_t lo, Py_ssize_t hi):
    """[(start, end)] of the `;`-terminated statements of text[lo:hi] at bracket depth 0 (`({[` against `)}]`)."""
    cdef Py_ssize_t i, start = lo
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list out = []
    if lo < 0 or hi > len(text):
        return NotImplemented
    for i in range(lo, hi):
        c = text[i]
        if c == u'(' or c == u'{' or c == u'[':
            depth += 1
        elif c == u')' or c == u'}' or c == u']':
            depth -= 1
        elif c == u';' and depth == 0:
            out.append((start, i + 1))
            start = i + 1
    return out


def paren_depth_table(str text, Py_ssize_t opening, Py_ssize_t end):
    """{offset: the parenthesis depth in front of it} for each offset of text[opening:end]."""
    cdef Py_ssize_t k
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef dict table = {}
    if opening < 0 or end > len(text):
        return NotImplemented
    for k in range(opening, end):
        table[k] = depth
        c = text[k]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
    return table


def conjuncts(str text, Py_ssize_t low, Py_ssize_t high):
    """The (start, end) offsets of the top-level `&&` operands of text[low:high] (parentheses and brackets balanced)."""
    cdef Py_ssize_t i = low, start = low
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list spans = []
    if low < 0 or high > len(text):
        return NotImplemented
    while i < high:
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif depth == 0 and text.startswith(u'&&', i):
            spans.append((start, i))
            start = i + 2
            i += 1
        i += 1
    spans.append((start, high))
    return spans


def statement_start_before(str text, Py_ssize_t at, Py_ssize_t floor):
    """Just after the `;`, `{` or `}` that ends the statement before the one containing `at` (outside parentheses),
    looking back from `at - 1` to `floor + 1`; `floor + 1` if there is none."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if floor < -1 or at - 1 >= len(text):
        return NotImplemented
    i = at - 1
    while i > floor:
        c = text[i]
        if c == u')':
            depth += 1
        elif c == u'(':
            depth -= 1
        elif depth <= 0 and (c == u';' or c == u'{' or c == u'}'):
            return i + 1
        i -= 1
    return floor + 1


def brace_balance(str text, Py_ssize_t start, Py_ssize_t end):
    """The net brace depth of text[start:end] (`{` minus `}`)."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'{':
            depth += 1
        elif c == u'}':
            depth -= 1
    return depth


def next_argument(str text, Py_ssize_t start):
    """The offset after the first top-level comma at or after `start` (brackets `([{` balanced), else len(text)."""
    cdef Py_ssize_t i, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if start < 0:
        return NotImplemented
    for i in range(start, length):
        c = text[i]
        if c == u'(' or c == u'[' or c == u'{':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
        if depth == 0 and c == u',':
            return i + 1
    return length
