"""`(x + 1) <= K` written as `x < K`: a bias m2c added to a bounded value before an unsigned compare.

A random roll in 1..100 compared with a percentage, `rand(100) + 1 <= 33`, is the game's `rand(100) < 33` when the roll
is a bounded count: m2c keeps the `+ 1` from the instruction sequence (`addiu v0,v0,1; sltiu v0,v0,0x22`) and the
compare against `K + 1`. The target has the bare compare, `sltiu v0,v0,0x21`: 4310 -> 4060 in a 970-instruction N64
state-machine handler (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) with this edit alone.

`variants` rewrites `(E + c) <= K` as `E <= K - c` (`E < K` for c = 1), `(E + c) < K` as `E < K - c` and `(E + c) >= K` as
`E >= K - c`, `(E + c) > K` as `E > K - c`, for a decimal or hexadecimal literal K (an `U` suffix kept) and a positive
c below K, where E is any balanced expression (a call included); and `(E + 1) <= (B)` with B a parenthesised
expression as `E < (B)` (a loop guard m2c wrote from `sltu`: on a 1928-instruction collision sweep `(i + 1) <= (u16)
rec->count` where the target has `sltu $v0, $s1, $v0`, 9064 -> 8884). One child per site and one with all of them, at
most 4. The rewrite is exact for a value that cannot wrap; the exact judge decides whether the compare was the game's.
"""
import re

from .integer_repair_support import view

FAMILY = 'compare_bias_fold'
FAMILIES = (FAMILY,)
LIMIT = 4
BOUNDED = re.compile(r'\+\s*1\s*\)\s*<=\s*\(')
SITE = re.compile(r'\+\s*(?P<c>0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*(?P<op><=|>=|<|>)(?![<>=])\s*(?P<k>0[xX][0-9A-Fa-f]+|\d+)(?P<u>[uU]?)\b')


def _python_open_of(clean, close):
    depth = 0
    for index in range(close, -1, -1):
        depth += (clean[index] == ')') - (clean[index] == '(')
        if depth == 0:
            return index
    return None


_open_of = _python_open_of
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _open_of(clean, close):
        found = _scan.open_every(clean, close, '(', ')', None)
        return _python_open_of(clean, close) if found is NotImplemented else found


def _number(value, like):
    return hex(value).upper().replace('0X', '0x') if like.lower().startswith('0x') else str(value)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    edits = []
    for hit in SITE.finditer(part.clean, part.opening, part.end):
        c, k = int(hit['c'], 0), int(hit['k'], 0)
        close = hit.start() + part.clean[hit.start():].index(')')
        start = _open_of(part.clean, close)
        if start is None or not 0 < c < k:
            continue
        inner = source[start + 1:hit.start()].rstrip()
        if not inner or re.search(r'[?:]|(?<![<>=!])=(?!=)|&&|\|\|', part.clean[start + 1:hit.start()]):
            continue
        bound = k - c
        op = hit['op']
        if op == '<=' and c == 1:
            op, bound = '<', k
        text = f'{inner} {op} {_number(bound, hit["k"])}{hit["u"]}'
        edits.append((start, hit.end(), text))
    for hit in BOUNDED.finditer(part.clean, part.opening, part.end):
        close = hit.start() + part.clean[hit.start():].index(')')
        start = _open_of(part.clean, close)
        if start is None:
            continue
        depth, end = 0, None
        for index in range(hit.end() - 1, part.end):
            depth += (part.clean[index] == '(') - (part.clean[index] == ')')
            if depth == 0:
                end = index + 1
                break
        inner = source[start + 1:hit.start()].rstrip()
        if end is None or not inner or re.search(r'[?:]|(?<![<>=!])=(?!=)|&&|\|\|', part.clean[start + 1:hit.start()]):
            continue
        edits.append((start, end, f'{inner} < {source[hit.end() - 1:end]}'))
    edits.sort()
    out = [source[:a] + text + source[b:] for a, b, text in edits]
    if len(edits) > 1:
        text = source
        for a, b, new in reversed(edits):
            text = text[:a] + new + text[b:]
        out.append(text)
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
