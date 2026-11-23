"""A snapshot of an address-taken frame local given back to the local, and copied again at the top of the block that uses it.

m2c keeps what a callee wrote into `locals.out` in a local (`phase_temp = locals.out;`) and uses it through a whole branch,
across calls. The compiler then gives that local a saved register for the whole span (`$s0`); the target read the frame
slot where the draft used the local (`lw $a0, 0x34($sp)` in the condition) and loaded it once more, into `$v0`, at the top of
the block that follows the calls (`lw $v0, 0x34($sp)` before the first field read there), so no register is held. Each half
alone was worse (the local inlined everywhere: 1420 -> 1470; the body copy alone 1420 -> 1410 with the saved register
still taken); both together went 1420 -> 1270 on a 1137-instruction player-update routine (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O2`). Hypothesis from the match: a block-local pseudo for the body copy ends before the next call,
so it takes a call-clobbered register and the saved one is not needed.

address_taken_snapshot_split
    `T = X;` (T a declared local of any type, X a member `local.field` whose address is taken elsewhere in the function)
    right before `if (C) {`, where C mentions T and the braced body of the first `if` nested inside it whose condition
    or body mentions T is B: one child drops the statement, reads X in C (and in the conditions between), declares `P`
    of T's type, writes `P = X;` first in B and reads P in B. T must not be mentioned after the outer `if`. At most 2 children."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'address_taken_snapshot_split'
FAMILIES = (FAMILY,)
LIMIT = 2
_SNAPSHOT = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<src>{IDENT}\.{IDENT})\s*;[ \t]*\n(?P<gap>[ \t]*\n)*')


def _mention(var):
    return re.compile(rf'(?<![\w.>]){re.escape(var)}\b')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    out = []
    for shot in _SNAPSHOT.finditer(clean, opening, span[1]):
        var, src = shot['var'], shot['src']
        if not re.search(rf'&\s*{re.escape(src)}\b', clean[opening:span[1]]):
            continue
        declared = re.search(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*?\*?)[ \t]*{re.escape(var)}[ \t]*;', clean[opening:shot.start()])
        if not declared or len(_mention(var).findall(clean, opening, span[1])) < 3:
            continue
        if len(re.findall(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', clean[opening:span[1]])) != 1:
            continue
        branch = re.compile(r'[ \t]*if\s*\(').match(clean, shot.end())
        if not branch:
            continue
        cond_stop = close(clean, branch.end() - 1, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, cond_stop or 0)
        if not cond_stop or not brace or not _mention(var).search(clean, branch.end(), cond_stop):
            continue
        body_open = brace.end() - 1
        body_stop = close(clean, body_open, '{', '}')
        if not body_stop or _mention(var).search(clean, body_stop, span[1]):
            continue
        inner = None
        for nested in re.finditer(r'\bif\s*\(', clean[body_open + 1:body_stop]):
            at = body_open + 1 + nested.start()
            stop = close(clean, at + nested.end() - nested.start() - 1, '(', ')')
            block = re.compile(r'\s*\{').match(clean, stop or 0)
            if not stop or not block:
                continue
            block_open = block.end() - 1
            block_stop = close(clean, block_open, '{', '}')
            if block_stop and _mention(var).search(clean, block_open, block_stop):
                inner = (at, stop, block_open, block_stop)
                break
        if not inner:
            continue
        at, stop, block_open, block_stop = inner
        copy = f'{var}_body'
        if re.search(rf'\b{copy}\b', clean):
            continue
        edits = []
        for use in _mention(var).finditer(clean, shot.end(), block_open):
            edits.append((use.start(), use.end(), src))
        for use in _mention(var).finditer(clean, block_open + 1, block_stop):
            edits.append((use.start(), use.end(), copy))
        edits.append((block_open + 1, block_open + 1, f'\n{shot["indent"]}    {copy} = {src};'))
        edits.append((shot.start(), shot.end(), ''))
        text = source
        for start, end, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[end:]
        body = text.find('\n', text.find('{', span[0])) + 1
        indent = re.match(r'[ \t]*', text[body:])[0] or '  '
        kind = re.sub(r'\s+', ' ', declared['type'].strip())
        text = text[:body] + f'{indent}{kind}{"" if kind.endswith("*") else " "}{copy};\n' + text[body:]
        out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
