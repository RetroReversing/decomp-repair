"""A call whose argument is a `?:`, made in each arm of an `if`/`else` instead.

    gfx = func_800434B0(gfx, (op[1] & 0xC0) ? 1 : 0);

GCC folds `c ? 1 : 0` into a set-on-condition (`sltu $a1, $zero, $a1`) and any other `?:` into a branch around the
argument register alone. A 618-instruction N64 display-list interpreter (SN64 GCC 2.8.1, `-mfp32`) branches around the
whole argument setup instead, each arm loading every argument and the two arms joining at one `jal`:

    beqz  $v0, .L1
    nop
    move  $a0, $s3
    j     .L2
    li    $a1, 1
    .L1: move $a0, $s3
    move  $a1, $zero
    .L2: jal func_800434B0

That is a call in each arm, `if (c) { gfx = f(gfx, 1); } else { gfx = f(gfx, 0); }`, the calls merged by cross-jumping
after allocation (the skill's "one call per branch"). 9751 -> 9346 in the isolated judge alone, 8756 with
`zero_guard_local`.

Children (`ternary_call_arms`, bounded): for a statement `f(..., c ? a : b, ...);` or `x = f(...);` whose one top-level
`?:` argument has no call or assignment in its condition, the `if`/`else` with the call in each arm, and the same with the
condition negated and the arms swapped; each also with the next simple statement (an assignment or step naming nothing the
call statement names) moved above the `if`, the order the interpreter needed (`op = cmd; n = ..; cmd += 2; if (..)`: 9486,
the split alone 10446).
"""
import re

from . import c_scan
from .csource import _blank, find

FAMILY = 'ternary_call_arms'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
NEXT = re.compile(rf'[ \t]*{IDENT}\s*(?:[-+*/|&^]?=[^;{{}}=][^;{{}}]*|\+\+|--);[ \t]*\n')
CALL = re.compile(rf'(?m)^([ \t]*)((?:{IDENT}\s*=\s*)?)({IDENT})\s*\(')


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def _python_split_args(clean, lo, hi):
    """(start, end) of each top-level argument in clean[lo:hi]."""
    out, depth, at = [], 0, lo
    for i in range(lo, hi):
        c = clean[i]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == ',' and depth == 0:
            out.append((at, i))
            at = i + 1
    out.append((at, hi))
    return out


_split_args = _python_split_args
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split_args(clean, lo, hi):
        found = _scan.argument_spans_all(clean, lo, hi)
        return _python_split_args(clean, lo, hi) if found is NotImplemented else found


def _ternary(text):
    """(condition, a, b) of a top-level `c ? a : b` (outer parentheses allowed), or None."""
    body = text.strip()
    while body.startswith('(') and c_scan.close(body, 0, '(', ')') == len(body) - 1:
        body = body[1:-1].strip()
    depth, q = 0, -1
    for i, c in enumerate(body):
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == '?' and depth == 0:
            q = i
            break
    if q < 0:
        return None
    depth = 0
    nested = 0
    for i in range(q + 1, len(body)):
        c = body[i]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == '?' and depth == 0:
            nested += 1
        elif c == ':' and depth == 0:
            if nested:
                nested -= 1
                continue
            return body[:q].strip(), body[q + 1:i].strip(), body[i + 1:].strip()
    return None


def _plain(expr):
    return not re.search(rf'{IDENT}\s*\(', expr) and not re.search(r'(?<![=!<>])=(?!=)|\+\+|--', expr)


def rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    result = []
    for hit in CALL.finditer(clean, opening, end):
        if hit[3] in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
            continue
        paren = hit.end() - 1
        close = c_scan.close(clean, paren, '(', ')')
        if close < 0 or close >= end or not re.match(r'\s*;', clean[close + 1:]):
            continue
        prev = clean[:hit.start(2)].rstrip()
        if prev and prev[-1] not in ';{}':
            continue  # the body of an unbraced `if`/`else`/loop: leave it alone
        semi = clean.index(';', close)
        args = _split_args(clean, paren + 1, close)
        picks = [(i, _ternary(source[a:b])) for i, (a, b) in enumerate(args)]
        picks = [(i, t) for i, t in picks if t]
        if len(picks) != 1:
            continue
        index, (cond, yes, no) = picks[0]
        if cond.startswith('(') and c_scan.close(cond, 0, '(', ')') == len(cond) - 1:
            cond = cond[1:-1].strip()
        if not _plain(cond) or any(_ternary(source[a:b]) for j, (a, b) in enumerate(args) if j != index):
            continue
        indent = hit[1]
        a, b = args[index]
        lead = re.match(r'\s*', source[a:b]).group()

        head, tail = source[hit.start(2):a] + lead, source[b:semi + 1]

        def call(value, head=head, tail=tail):
            return head + value + tail

        inner = indent + '    '
        after = semi + 1 + re.match(r'[ \t]*\n?', source[semi + 1:]).end()
        nxt = NEXT.match(clean, after)
        names = set(re.findall(IDENT, clean[hit.start(2):semi]))
        movable = nxt and not re.search(rf'{IDENT}\s*\(', nxt[0]) and not set(re.findall(IDENT, nxt[0])) & names
        for test, first, second in ((cond, yes, no), (f'!({cond})', no, yes)):
            split = (f'{indent}if ({test}) {{\n{inner}{call(first)}\n{indent}}} else {{\n'
                     f'{inner}{call(second)}\n{indent}}}')
            texts = [source[:hit.start()] + split + source[semi + 1:]]
            if movable:
                texts.append(source[:hit.start()] + source[after:nxt.end()] + split + '\n'
                             + source[nxt.end():])
            for text in texts:
                if text not in result:
                    result.append(text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
