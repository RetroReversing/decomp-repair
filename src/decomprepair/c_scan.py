"""Small scanners over comment-free C text (`csource._blank`'s output), shared by the loop-shape families.

Every function takes `clean`, the text with comments and strings blanked (same length as the source), so a brace
in a comment never counts. None of this is a parser: each answers one question the families ask of m2c-style code.
"""
import re

LOOP_HEADER = re.compile(r'(?:\b(?:for|while)\s*\(.*\)|\bdo)\s*$', re.S)


def _close(clean, opening, left='{', right='}'):
    """Index of the bracket closing the one at `opening`, or -1."""
    depth = 0
    for i in range(opening, len(clean)):
        c = clean[i]
        if c == left:
            depth += 1
        elif c == right:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _enclosing_block(clean, at, lo):
    """Index of the `{` of the innermost block around position `at` (not before `lo`), or -1."""
    depth = 0
    for i in range(at - 1, lo - 1, -1):
        c = clean[i]
        if c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                return i
            depth -= 1
    return -1


def _header_before(clean, opening):
    """The text of the statement header just before the `{` at `opening` (`if (...)`, `for (;;)`, `do`, ...)."""
    depth, i = 0, opening - 1
    while i >= 0:
        c = clean[i]
        if c == ')':
            depth += 1
        elif c == '(':
            depth -= 1
        elif depth == 0 and c in ';{}':
            break
        i -= 1
    return clean[i + 1:opening].strip()


close, enclosing_block, header_before = _close, _enclosing_block, _header_before
try:  # the typed walkers (native_build.py), when built: the same answers, several times faster
    from . import _scan
except ImportError:
    pass
else:
    _scan.python_c_close, _scan.python_enclosing_block, _scan.python_header_before = _close, _enclosing_block, _header_before
    close, enclosing_block, header_before = _scan.c_close, _scan.c_enclosing_block, _scan.c_header_before


def _own_loop_statements(clean, lo, hi, word):
    """Offsets in clean[lo:hi] of `word` (`continue`/`break`) that belong to the loop whose body is that range, not
    to a loop nested inside it (a `break` in a `switch` counts as nested, as it leaves the switch)."""
    stack, out, depth_paren, boundary = [], [], 0, lo - 1
    for i in range(lo, hi):
        c = clean[i]
        if c == '(':
            depth_paren += 1
        elif c == ')':
            depth_paren -= 1
        elif c == '{' and depth_paren == 0:
            header = clean[boundary + 1:i].strip()
            stack.append(bool(LOOP_HEADER.search(header)) or (word == 'break' and bool(re.search(r'\bswitch\s*\(.*\)$', header, re.S))))
            boundary = i
        elif c == '}' and depth_paren == 0:
            if stack:
                stack.pop()
            boundary = i
        elif c == ';' and depth_paren == 0:
            boundary = i
        elif clean.startswith(word, i) and not (i and (clean[i - 1].isalnum() or clean[i - 1] == '_')) \
                and not (i + len(word) < len(clean) and (clean[i + len(word)].isalnum() or clean[i + len(word)] == '_')):
            if not any(stack):
                out.append(i)
    return out


def normal(text):
    """`text` with every run of whitespace one space, to compare two statements."""
    return ' '.join(text.split())


def _header_opens_loop(header, word):
    return bool(LOOP_HEADER.search(header)) or (word == 'break' and bool(re.search(r'\bswitch\s*\(.*\)$', header, re.S)))


own_loop_statements = _own_loop_statements
if close is not _close:  # the typed walkers loaded above: the loop scan comes from the same kernel
    _scan.python_own_loop_statements, _scan.header_opens_loop = _own_loop_statements, _header_opens_loop
    own_loop_statements = _scan.c_own_loop_statements
