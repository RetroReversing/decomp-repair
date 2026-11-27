"""One edge of a `do { } while (0)` fence moved by a statement: the last or first one leaves it, or a neighbour joins it.

    do {                                        do {
        *(s16 *) (p + 0x10) = 0x1000;               *(s16 *) (p + 0x10) = 0x1000;
        *(s16 *) (p + 0xE) = 0x1000;       ->       *(s16 *) (p + 0xE) = 0x1000;
        *(s16 *) (p + 0xC) = 0x1000;            } while (0);
    } while (0);                                *(s16 *) (p + 0xC) = 0x1000;

A fence is a pair of loop notes. In GCC 2.7.2's scheduler (sched.c) the first insn after such a note depends on
everything before it, so which statement follows the closing note decides which insn the later loads can't pass. On a
62-instruction spawner (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) a fence round three halfword stores left the
byte store after it as that barrier, and two loads the target has above the byte store stayed below it; with the third
halfword store out of the fence it is the barrier, and 60 -> 0. The families that unwrap, merge, deepen or shift whole
fences (`operation_scope_*`, `wrapper_boundary_shift`) never narrow or widen one.

One child per fence and edge: one or two plain statements out at either end (the fence keeps at least one), and the
plain statement just after or just before it taken in. Declarations, control statements and fences whose own body has a
`break` or `continue` are left alone. A candidate rewrite: the exact judge decides. Evidence level: one function.
"""
import re

from .integer_repair_support import view
from .pattern_repairs import close
from .statement_scope_weight import _breaks_out, _statement_end

FAMILY_OUT = 'fence_edge_out'
FAMILY_IN = 'fence_edge_in'
FAMILIES = (FAMILY_OUT, FAMILY_IN)
LIMIT = 48
_DO = re.compile(r'\bdo\s*\{')
_SOLID = re.compile(r'\S')
_LATCH = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;')
_NOT_PLAIN = re.compile(
    r'(?:if|else|for|while|do|switch|case|default|return|goto|break|continue|typedef|static|extern|struct|union|enum|'
    r'const|volatile|register|unsigned|signed)\b'
    r'|[A-Za-z_]\w*\s*:(?!:)'
    r'|[A-Za-z_]\w*(?:\s+\**\s*|\s*\*+\s+)[A-Za-z_]\w*\s*(?:\[|=|;|,)')


def _plain(clean, start, end):
    """Whether CLEAN[start:end] is one expression statement (no braces, keyword, label or declaration)."""
    text = clean[start:end].strip()
    return bool(text) and text.endswith(';') and not set('{}#') & set(text) and not _NOT_PLAIN.match(text)


def _body(clean, at, stop):
    """[(start, end)] of the statements between AT and STOP, or None when one can't be delimited."""
    found = []
    while True:
        hit = _SOLID.search(clean, at, stop)
        if not hit:
            return found
        end = _statement_end(clean, hit.start(), stop)
        if end is None or end <= hit.start():
            return None
        found.append((hit.start(), end))
        at = end


def _after(clean, at, stop):
    """The (start, end) of the plain statement right after AT in the same block, or None."""
    hit = _SOLID.search(clean, at, stop)
    end = _statement_end(clean, hit.start(), stop) if hit else None
    return (hit.start(), end) if end and _plain(clean, hit.start(), end) else None


def _before(clean, at, floor):
    """The (start, end) of the plain statement right before AT in the same block, or None."""
    end = floor + len(clean[floor:at].rstrip())
    if end <= floor or clean[end - 1] != ';':
        return None
    after = max(floor, *(clean.rfind(mark, floor, end - 1) + 1 for mark in ';{}'))
    hit = _SOLID.search(clean, after, end)
    start = hit.start() if hit else end
    text = clean[start:end]
    # a `;` inside parentheses (a `for` header) cuts the text unbalanced
    if text.count('(') != text.count(')') or not _plain(clean, start, end):
        return None
    # `if (c) x = 1;` and `else x = 1;` are one statement with their head, never a statement that can move alone
    head = clean[floor:start].rstrip()
    return (start, end) if not head or head[-1] in ';{}' else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = {key: [] for key in ('out1', 'in', 'out2')}
    for hit in _DO.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        shut = close(clean, opening, '{', '}')
        latch = _LATCH.match(clean, shut) if shut else None
        if not latch:
            continue
        begin, last, stop = hit.start(), shut - 1, latch.end()
        statements = _body(clean, opening + 1, last)
        if statements is None or _breaks_out(clean[opening + 1:last]):
            continue
        head, tail = source[begin:opening + 1], source[last:stop]
        for count in (1, 2):
            if len(statements) <= count:
                break
            key = f'out{count}'
            if all(_plain(clean, *s) for s in statements[-count:]):
                cut = statements[-count][0]
                kept = source[opening + 1:cut].rstrip()
                moved = source[cut:last].rstrip()
                found[key].append((FAMILY_OUT, source[:begin] + head + kept + ' ' + tail + ' ' + moved + source[stop:]))
            if all(_plain(clean, *s) for s in statements[:count]):
                cut = statements[count - 1][1]
                moved = source[opening + 1:cut].strip()
                found[key].append((FAMILY_OUT, source[:begin] + moved + ' ' + head + source[cut:stop] + source[stop:]))
        following = _after(clean, stop, part.end - 1)
        if following and statements:
            taken = source[following[0]:following[1]]
            body = source[opening + 1:last].rstrip()
            found['in'].append((FAMILY_IN, source[:begin] + head + body + ' ' + taken + ' ' + tail + source[following[1]:]))
        previous = _before(clean, begin, part.opening + 1)
        if previous and statements:
            taken = source[previous[0]:previous[1]]
            found['in'].append((FAMILY_IN, source[:previous[0]] + head + ' ' + taken + source[opening + 1:stop]
                                + source[stop:]))
    return list(dict.fromkeys(found['out1'] + found['in'] + found['out2']))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
