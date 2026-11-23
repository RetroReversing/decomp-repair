"""An early exit that repeats the statements the function ends with, written once after an inverted test.

m2c (and a saved best that kept its shape) writes a guard that leaves early with the same stores the function's last
lines make:

    if (p == -1) { s->count = 0; return; }
    release(p);
    s->slot = -1;
    s->count = 0;
    return;

The game wrote the stores once: `if (p != -1) { release(p); s->slot = -1; } s->count = 0; return;`. The compiler
tail-merges the two exits either way, but the merged tail is only the same code when the branch reaches it directly:
with two stores the early exit is `bne`/`nop`/`j` around a copy of the store in the jump's delay slot; with one it is a
single branch-likely (`beql`) whose delay slot is the store, the jump's own three instructions gone (KMC GCC 2.7.2,
580 -> 180 in one 557-instruction function, where the only differing rows were that branch and its two neighbours).

A proposal takes an `if (C) { S return E; }` with no `else`, whose block goes on with `T S return E;` as its last
statements (S and E equal up to whitespace and the numbering of one helper's copies, `inline_fn2`/`inline_fn23`), and
writes `if (!C) { T } S return E;`. A test that is a single `==` or `!=` is inverted by changing the operator, any
other by `!( )`. T must hold no label, `goto` or declaration. The meaning is unchanged: both paths run S and return
E. MIPS only."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_return_tail_merge'
FAMILIES = (FAMILY,)
LIMIT = 6

_DECLARATION = re.compile(r'(?m)^\s*(?:unsigned|signed|const|static|struct|u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|'
                          r'int|char|short|long|float|double|void)\b')
_LABEL = re.compile(r'(?m)^\s*[A-Za-z_]\w*\s*:(?!:)')


def _norm(text):
    """The text without whitespace, one helper's numbered copies (`inline_fn2`, `inline_fn23`) written as one."""
    return re.sub(r'\binline_fn\d+', 'inline_fn', re.sub(r'\s+', '', text))


def _invert(condition):
    """The negation of an if-condition: an operator swap for one top-level comparison, else `!( )`."""
    text = condition.strip()
    masked, depth = [], 0
    for ch in text:
        depth += ch in '(['
        masked.append(' ' if depth else ch)
        depth -= ch in ')]'
    masked = ''.join(masked)
    if re.search(r'&&|\|\||\?|(?<![=!<>])=(?!=)', masked):
        return f'!({text})'
    hits = list(re.finditer(r'==|!=|<=|>=|(?<![<>-])<(?![<=])|(?<![<>-])>(?![>=])', masked))
    if len(hits) != 1:
        return f'!({text})'
    hit = hits[0]
    swap = {'==': '!=', '!=': '==', '<=': '>', '>=': '<', '<': '>=', '>': '<='}
    return f'{text[:hit.start()].rstrip()} {swap[hit[0]]} {text[hit.end():].lstrip()}'


def _enclosing_end(clean, start, limit):
    depth = 0
    for at in range(start, limit):
        if clean[at] == '{':
            depth += 1
        elif clean[at] == '}':
            if depth == 0:
                return at
            depth -= 1
    return None


def variants(source, name, arch='mips'):
    """Proposals: an early exit's repeated stores merged with the function's own ending."""
    span = find(source, name)
    if arch != 'mips' or not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    out = []
    for guard in re.finditer(r'\bif\s*\(', clean[opening:span[1]]):
        at = opening + guard.start()
        paren = opening + guard.end() - 1
        paren_end = close(clean, paren)
        if not paren_end:
            continue
        brace = re.compile(r'\s*\{').match(clean, paren_end)
        if not brace:
            continue
        body_end = close(clean, brace.end() - 1, '{', '}')
        if not body_end or re.compile(r'\s*else\b').match(clean, body_end):
            continue
        inner = clean[brace.end():body_end - 1]
        leave = re.search(r'\breturn\b[^;{}]*;\s*$', inner)
        if not leave or not inner[:leave.start()].strip() or '{' in inner[:leave.start()]:
            continue
        shared = _norm(inner)
        block_end = _enclosing_end(clean, body_end, span[1])
        if block_end is None:
            continue
        rest = clean[body_end:block_end]
        cuts = [m.end() for m in re.finditer(r'[;}]', rest)]
        for cut in cuts:
            if _norm(rest[cut:]) != shared:
                continue
            middle = source[body_end:body_end + cut]
            if not middle.strip() or re.search(r'\bgoto\b', middle) or _LABEL.search(clean[body_end:body_end + cut]) \
                    or _DECLARATION.search(clean[body_end:body_end + cut]):
                break
            condition = source[paren + 1:paren_end - 1]
            tail = source[body_end + cut:block_end]
            indent = re.search(r'[ \t]*$', source[:at])[0]
            text = (f'if ({_invert(condition)})\n{indent}{{{middle.rstrip()}\n{indent}}}\n{indent}'
                    + tail.lstrip())
            out.append((FAMILY, source[:at] + text + source[block_end:]))
            break
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 80}  # the registry: no caller wiring (registry.py)
