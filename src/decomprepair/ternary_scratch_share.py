"""One scratch local for a short difference and for a clamp's result, the way the game reused one variable for both.

Matched on an N64 strip blitter (SN GCC 2.8.1, `-G0 -mips3 -O2`, 477 instructions, 310 -> 0). The entry computed
`h = y1 - y0; texh = h + 1;` and the target kept the difference in `$v1` where the draft had it in `h`'s saved
register: `h` is set again later and lives across the calls, so global.c gives the whole pseudo `$s3`. A temporary of
its own (`texh = y1 - y0 + 1;`, or any other local that is only that difference) is block-local and local-alloc.c gives
it `$v0`, which the following `slti` is free to take only later. What the target had was one more variable, declared
and otherwise unused in the draft, that held the difference *and*, later, the result of a `MIN` inside a LoadBlock
command word: `(top = ((texw * n - 1) < 0x800 ? (texw * n - 1) : 0x7FF))`. That second web is live while the `?:`
compare's result sits in `$v0`, so the one multi-set pseudo conflicts with `$v0` and global.c gives it `$v1`, which is
the register the target's entry and clamp both use. Either edit alone scored 905 and 310; together the function was
exact (hypothesis from the match: the conflict is read from the -dg dumps, not from the compiler source).

ternary_scratch_share
    For a scratch local `L` (an integer local declared and never used, else a new one of the difference's type), each
    pair of statements `X = E; Y = ... X ...;` where `X` is a top-level local assigned elsewhere too, read once by the
    second statement and written again before any later read, and each conditional expression `(c ? a : b)` that is
    an operand inside a larger expression: one child with `L = E; Y = ... L ...;` and the conditional written
    `(L = (c ? a : b))`, and one child with each edit alone. The value of every expression is unchanged: `L` is not
    read anywhere else.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import enclosing_block
from .guarded_loop_for import _written_before_read
from .integer_repair_support import DECL, IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'ternary_scratch_share'
FAMILIES = (FAMILY,)
PAIRS = 4
CONDITIONALS = 4
LIMIT = 24
_INNER_GROUP = re.compile(r'\([^()]*\)')
_PAIR = re.compile(rf'(?P<x>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}]+);\s*'
                   rf'(?P<y>{IDENT})\s*=(?!=)\s*(?P<use>[^;{{}}]+);')


def _names(clean, name, low, high):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[low:high])
            if not re.search(r'->\s*$', clean[low:low + m.start()])]


def _locals(clean, low, end):
    """(name, type, declaration span) of every top-level integer local."""
    out = []
    for decl in DECL.finditer(clean, low, end):
        if enclosing_block(clean, decl.start(), low) < 0:
            out.append((decl['name'], re.sub(r'\s+', ' ', decl['type']), decl.span()))
    return out


def _pairs(clean, low, end, declared):
    """Spans of `X` in each `X = E; Y = ... X ...;` whose value of X lives only across those two statements."""
    found, position = [], low
    while True:
        m = _PAIR.search(clean, position, end)
        if not m:
            break
        position = m.start('y')  # the second statement may start the next pair
        x, y = m['x'], m['y']
        if x not in declared or x == y:
            continue
        prefix = clean[low:m.start()].rstrip()
        if prefix and prefix[-1] not in ';{}' or re.search(rf'(?<![\w.>]){re.escape(x)}\b', m['value']):
            continue
        uses = [u for u in re.finditer(rf'(?<![\w.>]){re.escape(x)}\b', m['use'])]
        if len(uses) != 1 or re.search(rf'&\s*{re.escape(x)}\b', clean[low:end]):
            continue
        writes = [w for w in _names(clean, x, low, end) if re.match(r'\s*=(?!=)', clean[low + w.end():])]
        if len(writes) < 2 or not _written_before_read(clean, m.end(), low, end, x):
            continue
        first = m.start('x')
        use = m.start('use') + uses[0].start()
        found.append(((first, first + len(x)), (use, use + len(x)), m.span()))
    return found[:PAIRS]


def _conditionals(clean, low, end):
    """(open, close) of each parenthesised `c ? a : b` that is an operand inside a larger expression."""
    found, seen = [], set()
    for mark in re.finditer(r'\?', clean[low:end]):
        at = low + mark.start()
        start = max(clean.rfind(';', low, at), clean.rfind('{', low, at), clean.rfind('}', low, at)) + 1
        stop = clean.find(';', at, end)
        if stop < 0:
            continue
        for paren in re.finditer(r'\(', clean[start:at]):
            opening = start + paren.start()
            past = close(clean, opening, '(', ')')
            closing = past - 1 if past else -1
            if closing < at or closing > stop or opening in seen:
                continue
            inner = clean[opening + 1:closing]
            flat = inner
            while _INNER_GROUP.search(flat):
                flat = _INNER_GROUP.sub(lambda g: ' ' * len(g.group()), flat)
            if '?' not in flat or ':' not in flat or re.match(rf'\s*{IDENT}\s*=(?!=)', inner):
                continue
            before = clean[start:opening]
            if re.search(r'[\w\]]\s*$', before):
                continue  # a call's argument list, not a group
            if re.fullmatch(rf'\s*(?:{IDENT}\s*=(?!=)\s*|return\s*)?', before) and not clean[closing + 1:stop].strip():
                continue  # the whole value of the statement: nothing to share
            seen.add(opening)
            found.append((opening, closing))
    # the innermost conditional of a nest first: its group is the one a macro's MIN wrote
    found.sort(key=lambda span: (span[1] - span[0], span[0]))
    return found[:CONDITIONALS]


def _free(clean, base):
    name, k = base, 2
    while re.search(rf'\b{name}\b', clean):
        name, k = f'{base}{k}', k + 1
    return name


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean, low, end = part.clean, part.opening + 1, part.end
    locals_ = _locals(clean, low, end)
    if not locals_:
        return []
    declared = {local: kind for local, kind, _ in locals_}
    pairs = _pairs(clean, low, end, declared)
    conditionals = _conditionals(clean, low, end)
    if not pairs or not conditionals:
        return []
    unused = [(local, kind) for local, kind, span in locals_ if not _names(clean, local, span[1], end)]
    scratches = [(local, kind, None) for local, kind in unused[:2]]
    if not scratches:
        kind = declared[clean[pairs[0][0][0]:pairs[0][0][1]]]
        last = locals_[-1][2][1]
        scratches = [(_free(clean, 'scratch'), kind, last)]
    children = []
    for scratch, kind, insert in scratches:
        declaration = [(insert, insert, f'\n    {kind} {scratch};')] if insert is not None else []

        def pair_edits(pair, scratch=scratch):
            return [(a, b, scratch) for a, b in pair[:2]]

        def conditional_edits(span, scratch=scratch):
            opening, closing = span
            return [(opening, opening + 1, f'({scratch} = ('), (closing, closing + 1, '))')]

        for pair in pairs:
            for span in conditionals:
                if pair[2][0] <= span[0] < pair[2][1]:
                    continue
                children.append(edit(source, declaration + pair_edits(pair) + conditional_edits(span)))
        for pair in pairs:
            children.append(edit(source, declaration + pair_edits(pair)))
        for span in conditionals:
            children.append(edit(source, declaration + conditional_edits(span)))
    out = []
    for text in dict.fromkeys(children):
        if text != source:
            out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
