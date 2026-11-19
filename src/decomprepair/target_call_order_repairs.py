"""Calls to one function written in the order the target makes them, read from which field each passes first.

A function that calls `g(p->x40, ...)` and `g(p->x44, ...)` one after the other can reach a draft with the two
calls swapped, and gcc keeps calls in source order. The target says which comes first: the field loaded into `$a0`
before each `jal g`. An N64 function was 720 points off with the calls swapped, 150 with them in the target's order
and the flag both read through the record's own pointer (`q + 0`, as the game did, rather than `base + 0x14`); with
the caller's parameter passed on and widened (existing families) it was exact.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_call_order'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
OFFSET = r'(0x[0-9A-Fa-f]+|\d+)'
# `q = (char *)(b) + K;` : a pointer derived from another by a constant
DERIVED = re.compile(r'(?m)^[ \t]*(?P<q>' + IDENT + r')\s*=\s*\(\s*char\s*\*\s*\)\s*\(\s*(?P<b>' + IDENT + r')\s*\)\s*\+\s*'
                     + OFFSET.replace('(', '(?P<k>', 1) + r'\s*;')


def _target_offsets(asm, callee):
    """The offset loaded into $a0 before each `jal callee`, in the target's order (None where it can't be told)."""
    lines = [line.split('*/')[-1].strip() for line in (asm or '').splitlines()]
    found, last = [], None
    for line in lines:
        if hit := re.match(r'lw\s+\$a0,\s*' + OFFSET + r'\(\$\w+\)', line):
            last = int(hit[1], 0)
        if re.match(r'jal\s+' + re.escape(callee) + r'\b', line):
            found.append(last)
            last = None
    return found


def _first_offset(args):
    hit = re.search(r'\+\s*' + OFFSET + r'\s*\)\s*\)\s*$', args[0]) if args else None
    return int(hit[1], 0) if hit else None


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    statements = list(re.finditer(r'(?m)^[ \t]*(?P<f>' + IDENT + r')\s*\((?P<args>.*)\);[ \t]*\n', clean[opening:end]))
    result = []
    i = 0
    while i < len(statements):
        run = [statements[i]]
        while i + len(run) < len(statements) and statements[i + len(run)]['f'] == run[0]['f'] \
                and statements[i + len(run)].start() == run[-1].end():
            run.append(statements[i + len(run)])
        i += len(run)
        if len(run) < 2:
            continue
        callee = run[0]['f']
        mine = [_first_offset(m2cfix._split_top_level(m['args'])) for m in run]
        target = [o for o in _target_offsets(asm, callee) if o is not None]
        if None in mine or len(set(mine)) != len(mine) or sorted(mine) != sorted(target[:len(mine)]) \
                or mine == target[:len(mine)]:
            continue
        order = [run[mine.index(o)] for o in target[:len(mine)]]
        start, stop = opening + run[0].start(), opening + run[-1].end()
        text = source[:start] + ''.join(source[opening + m.start():opening + m.end()] for m in order) + source[stop:]
        result.append((FAMILY, text))
        # and the fields read through a pointer derived from their base, as the game may have
        derived = _derive(text, opening, start, start + (stop - start))
        if derived and derived != text:
            result.append((FAMILY, derived))
    return result[:4]


def _derive(text, opening, start, stop):
    """In text[start:stop], `(char *)(b) + N` written through `q` (as `(char *)(q) + N-K`) where `q = (char *)(b) + K;`
    came before."""
    hit = None
    for hit in DERIVED.finditer(_blank(text), opening, start):
        pass
    if hit is None:
        return None
    q, b, k = hit['q'], hit['b'], int(hit['k'], 0)

    def through(m):
        n = int(m[1], 0)
        return f'(char *)({q}) + {hex(n - k) if n > k else 0})' if n >= k else m[0]
    body = re.sub(r'\(char \*\)\(' + re.escape(b) + r'\) \+ ' + OFFSET + r'\)', through, text[start:stop])
    return text[:start] + body + text[stop:]
