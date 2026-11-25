"""A condition's second operand carried by an integer local that is dead there: `if (a && b)` as `if (a && ((v = b) != 0))`.

A zero-extended call result held in a local that only the next few statements read (`v = (u16) f(); m = v & 0xFF;
n = v & 0xFF00;`) has one set. GCC 2.7.2's first scheduler (sched.c `birthing_insn_p`) launches the single-set
pseudo's defining insn as late as the argument reloads allow, so the `andi $v0,$v0,0xffff` came after them while the
target had it first; with a second set the insn keeps its place in the order. The second set cannot be a throw-away: it
has to be a value the function really computes, and it must not widen the pseudo's life where it conflicts with the
registers it needs. A condition value is one: the second test of `if (a & x) && (b & x)` is computed into `$v0` in
the target (`and $v0,$s3,$v1`), the same register the call result lives in earlier. Writing that test as
`((v = b & x) != 0)` with `v` the call-result local gave the target's order and its registers, 20 to 0 in one function
(after the load / sum split, 285 to 85 with the guard compare before).

A proposal rewrites the second operand of one `if (A && B)` (two operands, no side effects in either) into
`((v = B) != 0)` for each integer local `v` of the function that is dead there: every mention of `v` lies outside the
innermost loop around the `if`, and the first mention after that loop (if any) is a plain assignment; one proposal per
candidate `v`, nearest mention first. MIPS only.
"""
import re

from .csource import _blank, find

FAMILY = 'condition_value_reuse'
FAMILIES = (FAMILY,)
LIMIT = 12

_ID = r'[A-Za-z_]\w*'
_INT = r'(?:(?:unsigned|signed|register)\s+)*(?:u8|s8|u16|s16|u32|s32|int|long|short|char|unsigned)'
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\w\s*\(')


def _python_close(clean, start, left, right):
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(clean, start, left, right):
        found = _scan.close_every(clean, start, left, right, True, None)
        return _python_close(clean, start, left, right) if found is NotImplemented else found


def _split_and(condition):
    """(left, right) when the condition is exactly `A && B` at the top level, else None."""
    depth, cuts = 0, []
    for at, ch in enumerate(condition):
        depth += ch in '(['
        depth -= ch in ')]'
        if depth == 0 and condition[at:at + 2] == '&&':
            cuts.append(at)
    if len(cuts) != 1:
        return None
    return condition[:cuts[0]], condition[cuts[0] + 2:]


def _loop_around(clean, opening, at):
    """(start, end) of the innermost `do { } while`, `while ( ) { }` or `for ( ) { }` body that holds offset `at`, or None."""
    best = None
    for m in re.finditer(r'\b(do|while|for)\b', clean[opening:at]):
        pos = opening + m.end()
        if m[1] != 'do':
            lead = re.compile(r'\s*\(').match(clean, pos)
            end_paren = _close(clean, lead.end() - 1, '(', ')') if lead else None
            if not end_paren:
                continue
            pos = end_paren
        brace = re.compile(r'\s*\{').match(clean, pos)
        if not brace:
            continue
        start = brace.end() - 1
        end = _close(clean, start, '{', '}')
        if end and start < at < end and (best is None or start > best[0]):
            best = (start, end)
    return best


def _mentions(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text)]


def variants(source, name, arch='mips'):
    """Proposals: the second test of an `&&` pair written through a dead integer local."""
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    body = clean[opening:closing]
    locals_ = re.findall(rf'(?m)^[ \t]*{_INT}[ \t]+({_ID})[ \t]*;', body)
    out = []
    for guard in re.finditer(r'\bif\s*\(', body):
        at = opening + guard.start()
        paren = opening + guard.end() - 1
        paren_end = _close(clean, paren, '(', ')')
        parts = _split_and(clean[paren + 1:paren_end - 1]) if paren_end else None
        if not parts or _EFFECT.search(parts[0]) or _EFFECT.search(parts[1]):
            continue
        loop = _loop_around(clean, opening, at) or (opening, closing)
        right_start = paren + 1 + len(parts[0]) + 2
        right_end = paren_end - 1
        candidates = []
        for v in locals_:
            places = _mentions(clean[opening:closing], v)
            places = [opening + p for p in places]
            if any(loop[0] <= p < loop[1] for p in places) or re.search(rf'\b{v}\b', clean[paren + 1:paren_end - 1]):
                continue
            after = [p for p in places if p >= loop[1]]
            if after and not re.match(r'\s*=(?!=)', clean[after[0] + len(v):]):
                continue
            before = [p for p in places if p < loop[0]]
            candidates.append((max(before) if before else -1, v))
        for _, v in sorted(candidates, reverse=True):
            right = source[right_start:right_end]
            lead = len(right) - len(right.lstrip())
            value = right.strip()
            if value.startswith('(') and _close(value, 0, '(', ')') == len(value):
                value = value[1:-1].strip()
            new = source[:right_start + lead] + f'(({v} = {value}) != 0)' + source[right_end:]
            out.append((FAMILY, new))
    seen, unique = set(), []
    for item in out:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 60}  # the registry: no caller wiring (registry.py)
