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


# The harder tail: a group closed by an unmatched bracket, redundant outer parentheses, mixed bracket pairs, brace groups, the last
# operand, and a few statement ends with their own stop rules.

def unmatched_close(str text, Py_ssize_t start, str left, str right, object miss):
    """The first `right` at or after `start` that no `left` in text[start:] opened (an opener already open before `start`)."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if start < 0 or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    for i in range(start, len(text)):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            if depth == 0:
                return i
            depth -= 1
    return miss


def unwrap_parens(str text):
    """`text`, stripped, without parentheses that enclose all of it (repeatedly)."""
    cdef Py_ssize_t i, n
    cdef Py_ssize_t depth
    cdef Py_UCS4 c
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        n = len(text)
        for i in range(n):
            c = text[i]
            if c == u'(':
                depth += 1
            elif c == u')':
                depth -= 1
            if depth == 0 and i < n - 1:
                return text
        text = text[1:n - 1].strip()  # (explicit: a negative index is undefined with wraparound off)
    return text


def close_pairs(str text, Py_ssize_t start, str opens, str closes, bint past, bint every, object miss):
    """The index of the bracket closing the one at `start`, brackets being any of `opens` against any of `closes` (at most
    three each, mixed freely); depth tested at every character when `every`, else only after a closer; one past it if `past`."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef long o0 = -1, o1 = -1, o2 = -1, c0 = -1, c1 = -1, c2 = -1, ci
    cdef Py_UCS4 c
    cdef bint is_closer
    if start < 0 or len(opens) > 3 or len(closes) > 3:
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
    for i in range(start, len(text)):
        c = text[i]
        ci = <long>c
        is_closer = False
        if ci == o0 or ci == o1 or ci == o2:
            depth += 1
        elif ci == c0 or ci == c1 or ci == c2:
            depth -= 1
            is_closer = True
        if depth == 0 and (every or is_closer):
            return i + 1 if past else i
    return miss


def brace_groups(str text, Py_ssize_t start, Py_ssize_t end):
    """[(open, close)] of each outermost `{ }` group inside text[start:end]."""
    cdef Py_ssize_t i, opening = -1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list groups = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'{':
            if depth == 0:
                opening = i
            depth += 1
        elif c == u'}':
            depth -= 1
            if depth == 0 and opening >= 0:
                groups.append((opening, i))
    return groups


def last_operand(str text, str operator):
    """text after the last top-level `operator` (brackets `([{` balanced), or all of it."""
    cdef Py_ssize_t pos = 0, last = 0, length = len(text), op_length = len(operator)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, first
    if op_length == 0:
        return NotImplemented
    first = operator[0]
    while pos < length:
        c = text[pos]
        if c == u'(' or c == u'[' or c == u'{':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
        elif depth == 0 and c == first and text.startswith(operator, pos):
            last = pos + op_length
            pos += op_length - 1
        pos += 1
    return text[last:]


def open_if_floor(str text, Py_ssize_t closing, Py_ssize_t floor, str left, str right, object miss):
    """open_if, looking back no further than `floor` (inclusive)."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 open_char, close_char, c
    if closing >= len(text) or floor < 0 or len(left) != 1 or len(right) != 1 or left == right:
        return NotImplemented
    open_char = left[0]
    close_char = right[0]
    i = closing
    while i >= floor:
        c = text[i]
        if c == close_char:
            depth += 1
        elif c == open_char:
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return miss


def simple_statement_end(str text, Py_ssize_t at):
    """One past the `;` ending the simple statement starting at `at`; None at a `{` or `}` outside brackets `([`."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if at < 0:
        return NotImplemented
    for i in range(at, len(text)):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif depth == 0 and (c == u'{' or c == u'}'):
            return None
        elif depth == 0 and c == u';':
            return i + 1
    return None


def statement_end_nonpositive(str text, Py_ssize_t start, Py_ssize_t end):
    """One past the first `;` before `end` whose bracket depth (`([{` against `)]}`) is zero or below; None otherwise."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'(' or c == u'[' or c == u'{':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
        if c == u';' and depth <= 0:
            return i + 1
    return None


def index_end(str text, Py_ssize_t at):
    """The `)` that closes a group of depth 1 opened before `at`; None at a `;`, `{` or `}` first."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 1
    cdef Py_UCS4 c
    if at < 0:
        return NotImplemented
    for i in range(at, len(text)):
        c = text[i]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
            if depth == 0:
                return i
        elif c == u';' or c == u'{' or c == u'}':
            return None
    return None


# The last of the plain scanners: operand and argument splits, a first `==`, an arm's end, and where a comparison's side begins and ends.

def top_plus(str text, Py_ssize_t start, Py_ssize_t end):
    """[(begin, end)] of the operands of the depth-0 `+` operators of text[start:end] (not `++`)."""
    cdef Py_ssize_t at, begin = start, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, prev
    cdef list spans = []
    if start < 0 or end > length:
        return NotImplemented
    for at in range(start, end):
        c = text[at]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif c == u'+' and depth == 0:
            prev = text[length - 1] if at == 0 else text[at - 1]  # the plain scan's text[at - 1] wraps at 0
            if prev != u'+' and (at + 1 >= length or text[at + 1] != u'+'):
                spans.append((begin, at))
                begin = at + 1
    spans.append((begin, end))
    return spans


def split_args_paren(str text, Py_ssize_t start, Py_ssize_t end):
    """[(begin, end)] of the top-level comma-separated arguments of text[start:end] (`([` against `)]`); the last always."""
    cdef Py_ssize_t i, at = start
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list spans = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif c == u',' and depth == 0:
            spans.append((at, i))
            at = i + 1
    spans.append((at, end))
    return spans


def argument_spans_all(str text, Py_ssize_t start, Py_ssize_t end):
    """argument_spans, the last span always kept (brackets `([{`)."""
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
    spans.append((begin, end))
    return spans


def sum_operands(str text, Py_ssize_t start, Py_ssize_t end):
    """[(begin, end)] of each top-level operand of a sum in text[start:end] (`+` not `++` or `+=`); [] if it is no sum."""
    cdef Py_ssize_t i, begin = start, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, nxt, prev
    cdef list parts = []
    if start < 0 or end > length:
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        if depth == 0 and c == u'+':
            if i + 1 >= length:
                continue  # the plain scan's `'' not in '+='` is False at the end of the text
            nxt = text[i + 1]
            if nxt == u'+' or nxt == u'=':
                continue
            if i > 0 and text[i - 1] == u'+':  # (at i = 0 the plain scan's slice is empty, so not a `+`)
                continue
            parts.append((begin, i))
            begin = i + 1
    if not parts or depth:
        return []
    parts.append((begin, end))
    return parts


def first_top(str text, Py_ssize_t begin, Py_ssize_t end, str separator):
    """The first offset in text[begin:end] of `separator` at bracket depth 0 (`([{`), else -1."""
    cdef Py_ssize_t i
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, sep
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
            return i
    return -1


def top_level_equal(str text):
    """The offset of the first `==` outside brackets (`([`) that is not part of `!==`, `<==`, `>===` or `===`; None if none."""
    cdef Py_ssize_t pos, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, prev
    for pos in range(length - 1):
        c = text[pos]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        if depth == 0 and c == u'=' and text[pos + 1] == u'=':
            if pos == 0:
                continue  # the plain scan's `'' not in '!<>='` is False at the start
            prev = text[pos - 1]
            if prev == u'!' or prev == u'<' or prev == u'>' or prev == u'=':
                continue
            if pos + 2 < length and text[pos + 2] == u'=':
                continue
            return pos
    return None


def arm_end(str text, Py_ssize_t at):
    """The first `:`, `)`, `]`, `;` or `,` outside any brackets from `at` (a closer at depth 0, or `:;,`); len(text) if none."""
    cdef Py_ssize_t i, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    if at < 0:
        return NotImplemented
    for i in range(at, length):
        c = text[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0 and (c == u':' or c == u';' or c == u','):
            return i
    return length


def and_cuts(str text):
    """The offsets of each `&&` outside brackets (`([`), overlapping ones included."""
    cdef Py_ssize_t at, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list cuts = []
    for at in range(length - 1):
        c = text[at]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        if depth == 0 and c == u'&' and text[at + 1] == u'&':
            cuts.append(at)
    return cuts


def depth_text(str text, Py_ssize_t start, Py_ssize_t end):
    """text[start:end] with every nested block (and the braces) blanked, so only the block's own statements show."""
    cdef Py_ssize_t index
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list out = []
    if start < 0 or end > len(text):
        return NotImplemented
    for index in range(start, end):
        c = text[index]
        if c == u'{':
            depth += 1
            out.append(u' ')
        elif c == u'}':
            depth -= 1
            out.append(u' ')
        else:
            out.append(c if depth == 0 else u' ')
    return ''.join(out)


cdef inline bint _boundary_char(Py_UCS4 c):
    return c == u',' or c == u';' or c == u'{' or c == u'}' or c == u'?' or c == u':'


def left_boundary(str text, Py_ssize_t at, Py_ssize_t lo):
    """Just after the `(` that opens the group around `at`, or after the nearest `,;{}?:`, `&&`, `||` or plain `=` before it
    (looking back from `at - 1` to `lo`); `lo` if none."""
    cdef Py_ssize_t j
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, p
    if lo < 1 or at > len(text) - 1 or at < 1:
        return NotImplemented
    j = at - 1
    while j >= lo:
        c = text[j]
        if c == u')':
            depth += 1
        elif c == u'(':
            if depth == 0:
                return j + 1
            depth -= 1
        elif depth == 0:
            p = text[j - 1]
            if _boundary_char(c) or ((c == u'&' or c == u'|') and p == c):
                return j + 1
            if c == u'=' and not (p == u'=' or p == u'!' or p == u'<' or p == u'>') and text[j + 1] != u'=':
                return j + 1
        j -= 1
    return lo


def right_boundary(str text, Py_ssize_t at, Py_ssize_t hi):
    """The `)` that closes the group around `at`, or the nearest `,;{}?:`, `&&`, `||` or plain `=` after it; `hi` if none."""
    cdef Py_ssize_t j, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, p
    if at < 1 or hi > length:
        return NotImplemented
    for j in range(at, hi):
        c = text[j]
        if c == u'(':
            depth += 1
        elif c == u')':
            if depth == 0:
                return j
            depth -= 1
        elif depth == 0:
            if _boundary_char(c) or ((c == u'&' or c == u'|') and j + 1 < length and text[j + 1] == c):
                return j
            if c == u'=' and (j + 1 >= length or text[j + 1] != u'=') and not (
                    text[j - 1] == u'=' or text[j - 1] == u'!' or text[j - 1] == u'<' or text[j - 1] == u'>'):
                return j
    return hi


def blocks_two_deep(str text, Py_ssize_t opening, Py_ssize_t end):
    """[(start, end)] of the brace blocks whose `}` closes at depth 2 (a function body's own blocks and their arms),
    sorted. An unbalanced `}` (no opener left) is the plain scan's IndexError: it is left to it."""
    cdef Py_ssize_t pos, start
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list starts = []
    cdef list out = []
    if opening < 0 or end > len(text):
        return NotImplemented
    for pos in range(opening, end):
        c = text[pos]
        if c == u'{':
            depth += 1
            starts.append(pos)
        elif c == u'}':
            if not starts:
                return NotImplemented
            start = starts.pop()
            if depth == 2:
                out.append((start, pos + 1))
            depth -= 1
    return sorted(out)


def macro_arguments(str text, Py_ssize_t start):
    """(offset past the `)`, [(begin, end)] of the two arguments) of a macro call whose arguments begin at `start`, split at
    parenthesis depth 0 (inside [] or {} too); (None, []) when there are not exactly two or it never closes."""
    cdef Py_ssize_t pos, first = start
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list parts = []
    if start < 0:
        return NotImplemented
    for pos in range(start, len(text)):
        c = text[pos]
        if c == u'(':
            depth += 1
        elif c == u')':
            if depth == 0:
                parts.append((first, pos))
                if len(parts) == 2:
                    return pos + 1, parts
                return None, []
            depth -= 1
        elif c == u',' and depth == 0:
            parts.append((first, pos))
            first = pos + 1
    return None, []


# Block pairing and a few splitters that the first sweeps missed (they keep a stack rather than a depth).

def brace_pairs_strict(str text, Py_ssize_t lo, Py_ssize_t hi):
    """{index of `{`: index of its `}`} for the braces in text[lo:hi]; None when they do not pair."""
    cdef Py_ssize_t at
    cdef Py_UCS4 c
    cdef list stack = []
    cdef dict found = {}
    if lo < 0 or hi > len(text):
        return NotImplemented
    for at in range(lo, hi):
        c = text[at]
        if c == u'{':
            stack.append(at)
        elif c == u'}':
            if not stack:
                return None
            found[stack.pop()] = at
    return None if stack else found


def block_pairs(str text, Py_ssize_t start, Py_ssize_t end):
    """[(open, close)] of every `{ }` pair in text[start:end], in the order they close (a stray `}` is ignored)."""
    cdef Py_ssize_t i
    cdef Py_UCS4 c
    cdef list stack = []
    cdef list found = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'{':
            stack.append(i)
        elif c == u'}' and stack:
            found.append((stack.pop(), i))
    return found


def open_stack(str text, Py_ssize_t start, Py_ssize_t at):
    """The offsets of the `{` still open at `at`, counted from `start` (a stray `}` is ignored)."""
    cdef Py_ssize_t i
    cdef Py_UCS4 c
    cdef list stack = []
    if start < 0 or at > len(text):
        return NotImplemented
    for i in range(start, at):
        c = text[i]
        if c == u'{':
            stack.append(i)
        elif c == u'}' and stack:
            stack.pop()
    return stack


def top_plus_index(str text):
    """The offset of the first `+` outside parentheses that is not part of `++`, else -1."""
    cdef Py_ssize_t index, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c, prev
    for index in range(length):
        c = text[index]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
        if depth == 0 and c == u'+':
            prev = text[length - 1] if index == 0 else text[index - 1]  # the plain scan's text[index - 1] wraps at 0
            if prev != u'+' and (index + 1 >= length or text[index + 1] != u'+'):
                return index
    return -1


def line_starts_at_depth_one(str text):
    """The set of offsets that begin a line (or the text) while the brace depth is 1 and are not themselves a brace."""
    cdef Py_ssize_t index
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef set offsets = set()
    for index in range(len(text)):
        c = text[index]
        if c == u'{':
            depth += 1
        elif c == u'}':
            depth -= 1
        elif depth == 1 and (index == 0 or text[index - 1] == u'\n'):
            offsets.add(index)
    return offsets


def statements_brace_reset(str text, Py_ssize_t start, Py_ssize_t end):
    """[(start, end)] of each `;`-ended statement in text[start:end] (start past leading space); a brace ends a run."""
    cdef Py_ssize_t i, begin = start, lead
    cdef Py_UCS4 c
    cdef list out = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'{' or c == u'}':
            begin = i + 1
        elif c == u';':
            lead = begin
            while lead < i + 1 and text[lead].isspace():
                lead += 1
            out.append((lead, i + 1))
            begin = i + 1
    return out


def split_spaced_operator(str expr, str op):
    """The offset of the first `op` outside parentheses with a space on each side, else -1. A match at offset 0 or at the
    very end is left to the plain scan (it reads a character it has no right to there)."""
    cdef Py_ssize_t i, length = len(expr), op_length = len(op)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    for i in range(length):
        c = expr[i]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
        elif depth == 0 and expr.startswith(op, i):
            if i == 0 or i + op_length >= length:
                return NotImplemented
            if expr[i - 1] == u' ' and expr[i + op_length] == u' ':
                return i
    return -1


def call_argument_count(str text, Py_ssize_t start):
    """(the argument count of the call whose `(` is at or after `start`, the offset after its `)`); None if unbalanced."""
    cdef Py_ssize_t i, count = 0
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef bint saw = False
    if start < 0:
        return NotImplemented
    for i in range(start, len(text)):
        c = text[i]
        if c == u'(':
            depth += 1
            if depth == 1:
                continue
        elif c == u')':
            depth -= 1
            if depth == 0:
                return (count + 1 if saw else 0), i + 1
        elif c == u',' and depth == 1:
            count += 1
        if depth >= 1 and not c.isspace():
            saw = True
    return None


# Statement splitters. They differ in small ways (which brackets count, what resets a statement, whether an `else`/`while` after a
# closing brace continues it), so each is its own kernel, named for the module's own wording.

cdef inline bint _word_char(Py_UCS4 c):
    return c.isalnum() or c == u'_'


cdef bint _continues(str text, Py_ssize_t pos, Py_ssize_t end, bint allow_while):
    """`re.match(r'\\s*(?:else|while)\\b', text[pos:end])` (only `else` when not allow_while)."""
    cdef Py_ssize_t p = pos, e
    while p < end and text[p].isspace():
        p += 1
    if p + 4 <= end and text.startswith(u'else', p):
        e = p + 4
        return e >= end or not _word_char(text[e])
    if allow_while and p + 5 <= end and text.startswith(u'while', p):
        e = p + 5
        return e >= end or not _word_char(text[e])
    return False


def statements_record_init(str text, Py_ssize_t start, Py_ssize_t end):
    """record_init_shapes: [(begin, end)] of each top-level statement; a braced block is one statement unless `else`/`while` follows."""
    cdef Py_ssize_t pos, begin = -1
    cdef Py_ssize_t depth = 0, parens = 0
    cdef Py_UCS4 ch
    cdef list out = []
    if start < 0 or end > len(text):
        return NotImplemented
    for pos in range(start, end):
        ch = text[pos]
        if begin < 0 and not ch.isspace():
            begin = pos
        if ch == u'(':
            parens += 1
        elif ch == u')':
            parens -= 1
        elif ch == u'{':
            depth += 1
        elif ch == u'}':
            depth -= 1
            if depth == 0 and not _continues(text, pos + 1, end, True):
                out.append((begin, pos + 1))
                begin = -1
        elif ch == u';' and depth == 0 and parens == 0:
            out.append((begin, pos + 1))
            begin = -1
    return out


def statements_scheduling(str text, Py_ssize_t start, Py_ssize_t closing):
    """scheduling_scope: [(start, end)] of each top-level statement in text[start:closing], all brackets counted together."""
    cdef Py_ssize_t i, begin = -1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list out = []
    if start < 0 or closing > len(text):
        return NotImplemented
    for i in range(start, closing):
        c = text[i]
        if begin < 0 and not c.isspace():
            begin = i
        if c == u'(' or c == u'{' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif c == u'}':
            depth -= 1
            if depth == 0 and begin >= 0:
                if not _continues(text, i + 1, closing, True):
                    out.append((begin, i + 1))
                    begin = -1
        elif c == u';' and depth == 0 and begin >= 0:
            out.append((begin, i + 1))
            begin = -1
    return out


def statements_skip_join(str text, Py_ssize_t start, Py_ssize_t end):
    """skip_join_loop_wrapper: [(begin, end)] of each top-level statement; only `(` `{` against `)` `}` count."""
    cdef Py_ssize_t i, begin = -1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 ch
    cdef list out = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        ch = text[i]
        if begin < 0 and not ch.isspace():
            begin = i
        if ch == u'(' or ch == u'{':
            depth += 1
        elif ch == u')' or ch == u'}':
            depth -= 1
            if depth == 0 and ch == u'}':
                if not _continues(text, i + 1, end, True):
                    out.append((begin, i + 1))
                    begin = -1
        elif ch == u';' and depth == 0 and begin >= 0:
            out.append((begin, i + 1))
            begin = -1
    return out


def statements_counter_split(str text, Py_ssize_t start, Py_ssize_t end):
    """loop_counter_value_split: [(start, end)] of each top-level statement, each starting where the last ended (spaces kept)."""
    cdef Py_ssize_t i, at = start
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list out = []
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        c = text[i]
        if c == u'(' or c == u'{' or c == u'[':
            depth += 1
        elif c == u')' or c == u'}' or c == u']':
            depth -= 1
            if depth == 0 and c == u'}':
                if not _continues(text, i + 1, end, True):
                    out.append((at, i + 1))
                    at = i + 1
        elif c == u';' and depth == 0:
            out.append((at, i + 1))
            at = i + 1
    return out


def statements_pair_share(str text, Py_ssize_t lo, Py_ssize_t hi):
    """call_pair_address_share: [(start, end)] of each simple statement ending in `;` at parenthesis depth 0, at any brace nesting."""
    cdef Py_ssize_t i, start = -1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list out = []
    if lo < 0 or hi > len(text):
        return NotImplemented
    for i in range(lo, hi):
        c = text[i]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
        elif depth == 0 and (c == u'{' or c == u'}'):
            start = -1
        elif depth == 0 and c == u';':
            if start >= 0:
                out.append((start, i + 1))
            start = -1
        elif start < 0 and not c.isspace() and depth == 0:
            start = i
    return out


def statements_arm_roles(str text, Py_ssize_t start, Py_ssize_t end):
    """float_arm_roles: the arm's top-level statements as (start, end), None in a nested block's place; None when unbalanced."""
    cdef Py_ssize_t pos, at = -1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list result = []
    if start < 0 or end > len(text):
        return NotImplemented
    for pos in range(start, end):
        c = text[pos]
        if at < 0 and not c.isspace() and depth == 0 and c != u'{' and c != u'}':
            at = pos
        if c == u'(' or c == u'{' or c == u'[':
            depth += 1
        elif c == u')' or c == u'}' or c == u']':
            depth -= 1
            if c == u'}' and depth == 0:
                result.append(None)
                at = -1
        elif c == u';' and depth == 0 and at >= 0:
            result.append((at, pos + 1))
            at = -1
    return result if at < 0 and depth == 0 else None


def top_statement_starts(str text, Py_ssize_t start, Py_ssize_t stop):
    """arm_result_constant_sink: the start offsets of the statements at the top level of text[start:stop]."""
    cdef Py_ssize_t at
    cdef Py_ssize_t depth = 0
    cdef bint fresh = True
    cdef Py_UCS4 c
    cdef list starts = []
    if start < 0 or stop > len(text):
        return NotImplemented
    for at in range(start, stop):
        c = text[at]
        if fresh and not c.isspace():
            if depth == 0:
                starts.append(at)
            fresh = False
        if c == u'(' or c == u'{' or c == u'[':
            depth += 1
        elif c == u')' or c == u']' or c == u'}':
            depth -= 1
            if c == u'}' and depth == 0:
                fresh = True
        elif c == u';' and depth == 0:
            fresh = True
    return starts


def split_operator(str e, str op):
    """`e` cut at each top-level binary `op` (not inside parentheses or brackets; a one-character `op` is not part of a doubled
    one or `op=`), each part stripped."""
    cdef Py_ssize_t i = 0, start = 0, length = len(e), op_length = len(op)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list parts = []
    cdef str before, after
    if op_length == 0:
        return NotImplemented
    while i < length:
        c = e[i]
        if c == u'(' or c == u'[':
            depth += 1
        elif c == u')' or c == u']':
            depth -= 1
        elif depth == 0 and e.startswith(op, i):
            before = e[i - 1:i] if i > 0 else ''
            after = e[i + op_length:i + op_length + 1]
            if op_length == 1 and (before == op or after == op or after == '='):
                i += 1
                continue
            parts.append(e[start:i])
            start = i + op_length
            i = start
            continue
        i += 1
    parts.append(e[start:])
    return [p.strip() for p in parts]


def parameter_texts(str text, Py_ssize_t opening, Py_ssize_t stop):
    """The stripped text of each top-level parameter of the list opened at `opening` (read up to `stop`)."""
    cdef Py_ssize_t index, begin = opening + 1
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 c
    cdef list found = []
    if opening < 0 or stop > len(text):
        return NotImplemented
    for index in range(opening, stop):
        c = text[index]
        if c == u'(':
            depth += 1
        elif c == u')':
            depth -= 1
        if (c == u',' and depth == 1) or (c == u')' and depth == 0):
            found.append(text[begin:index].strip())
            begin = index + 1
            if depth == 0:
                break
    return found


def block_chains(str text, Py_ssize_t start, Py_ssize_t end):
    """[(open, close, (enclosing opens...))] of every `{ }` block in text[start:end], in the order they close."""
    cdef Py_ssize_t index, opening
    cdef Py_UCS4 c
    cdef list stack = []
    cdef list found = []
    if start < 0 or end > len(text):
        return NotImplemented
    for index in range(start, end):
        c = text[index]
        if c == u'{':
            stack.append(index)
        elif c == u'}' and stack:
            opening = stack.pop()
            found.append((opening, index, tuple(stack)))
    return found


def open_stack_strict(str text, Py_ssize_t start, Py_ssize_t at):
    """open_stack, but a stray `}` is left to the plain scan (which raises IndexError there)."""
    cdef Py_ssize_t i
    cdef Py_UCS4 c
    cdef list stack = []
    if start < 0 or at > len(text):
        return NotImplemented
    for i in range(start, at):
        c = text[i]
        if c == u'{':
            stack.append(i)
        elif c == u'}':
            if not stack:
                return NotImplemented
            stack.pop()
    return stack


def bracket_chains(str text, Py_ssize_t start, Py_ssize_t end):
    """or_chain_order_repairs: (begin, end) of each maximal expression between delimiters that holds a single `|`."""
    cdef Py_ssize_t i, begin = start
    cdef Py_UCS4 ch
    cdef list found = []
    cdef list stack = []
    cdef str span
    if start < 0 or end > len(text):
        return NotImplemented
    for i in range(start, end):
        ch = text[i]
        if ch == u'(' or ch == u'[':
            stack.append(begin)
            begin = i + 1
        elif ch == u')' or ch == u']':
            if stack:
                span = text[begin:i]
                if '|' in span.replace('||', ''):
                    found.append((begin, i))
                begin = stack.pop()
        elif (ch == u';' or ch == u'{' or ch == u'}' or ch == u'=' or ch == u',') and not stack:
            span = text[begin:i]
            if '|' in span.replace('||', ''):
                found.append((begin, i))
            begin = i + 1
    return found


def operator_cuts(str text, str operators):
    """allocation_lever_repairs: [(offset, operator)] of each top-level commutative operator (not `&&`, `||`, `++`, `+=`, a
    dereference or pointer cast `*`, or `op=`)."""
    cdef Py_ssize_t i, j, length = len(text)
    cdef Py_ssize_t depth = 0
    cdef Py_UCS4 ch, before, after
    cdef bint has_before, has_after, ok
    cdef list cuts = []
    for i in range(length):
        ch = text[i]
        if ch == u'(' or ch == u'[':
            depth += 1
        elif ch == u')' or ch == u']':
            depth -= 1
        if depth == 0 and operators.find(ch) >= 0:
            has_before = i > 0
            has_after = i + 1 < length
            before = text[i - 1] if has_before else u'\0'
            after = text[i + 1] if has_after else u'\0'
            if (ch == u'&' or ch == u'|') and ((has_after and after == ch) or (has_before and before == ch)):
                continue
            if ch == u'*':
                j = i - 1
                while j >= 0 and text[j].isspace():
                    j -= 1
                ok = j >= 0 and (_word_char(text[j]) or text[j] == u')' or text[j] == u']')
                if not ok:
                    continue
            if (ch == u'+' or ch == u'-') and (not has_after or after == u'+' or after == u'=' or (has_before and before == ch)):
                continue
            if has_after and after == u'=':
                continue
            cuts.append((i, chr(ch)))
    return cuts


def statement_start_in_block(str text, Py_ssize_t block, Py_ssize_t first):
    """late_aggregate_scope: where the statement holding `first` begins inside the block opened at `block`, before skipping spaces; -1 if
    its braces do not balance."""
    cdef Py_ssize_t position
    cdef Py_ssize_t brace = 0, paren = 0
    cdef Py_ssize_t start = block + 1
    cdef Py_UCS4 c
    if block + 1 < 0 or first > len(text):
        return NotImplemented
    for position in range(block + 1, first):
        c = text[position]
        if c == u'(' or c == u'[':
            paren += 1
        elif c == u')' or c == u']':
            paren -= 1
        elif c == u'{':
            brace += 1
        elif c == u'}':
            brace -= 1
            if brace == 0 and paren == 0:
                start = position + 1
        elif c == u';' and brace == 0 and paren == 0:
            start = position + 1
    if brace:
        return -1
    return start
