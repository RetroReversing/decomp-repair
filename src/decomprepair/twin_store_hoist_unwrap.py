"""A second store of the same value moved up beside its first, and the one-shot `do { } while (0)` scopes dropped, as one child.

m2c writes a record's stores in the order the decompiler met them, so two halfword stores of one value (`p[0x4E] = v;`
and, three stores later, `p[0x50] = v;`) are apart, and the function's `do { } while (0)` scaffolding (a one-shot
scope) stands round the rest. On a KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 142-instruction object-setup
function the saved best scored 60 (the second store three places late). The store moved up beside its twin alone scored
120, the scopes dropped alone 60 (no change), and both together scored 0, so a greedy chain, which keeps only a step
that improves, never takes either. Hypothesis, read from the second scheduler's dump (`-dR`): its stack-argument
reloads (`lbu t0, N(sp)`) sit between two stores through the record in the target. A store the reload's use follows
gets an anti-dependence on the reload, so it can only come after it; a store written earlier is free to stay before it.
Dropping the scopes then moves the priority of the `li -1` that follows past the `sll` of the packed word, which is the
last difference (a hypothesis about the priorities; the measured result is the evidence, and the exact judge decides).

Only a faithful reorder is offered: both stores go through the same base to non-overlapping offsets of a known width,
the value is the same text, free of memory reads and calls, and made of locals or parameters whose address is never
taken; each store between them goes through the same base to another non-overlapping offset (so it cannot read what
moved or change what the value names). Offered twice, with the scopes dropped (`twin_store_hoist_unwrap`) and without
(`twin_store_hoist`, the chain's second step for a function that has no scopes).
"""
import re

from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, integer, view
from .macro_scope_weight import CONTROL, _blank
from .pattern_repairs import close

FAMILIES = ('twin_store_hoist', 'twin_store_hoist_unwrap')
LIMIT = 6
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4}
STORE = re.compile(
    r'\*\s*\(\s*\(\s*(?P<type>' + '|'.join(WIDTH) + r')\s*\*\s*\)\s*\(\s*(?P<base>' + IDENT + r')\s*\+\s*(?P<offset>' + NUMBER +
    r')\s*\)\s*\)\s*=\s*(?P<value>[^;{}=]+?)\s*;')
KEYWORD = {'sizeof', 'unsigned', 'signed', 'char', 'short', 'int', 'long', 'void', 'const'}


def runs(part):
    """Maximal runs of consecutive store statements of the function (nothing but empty statements between them)."""
    found, current, last = [], [], None
    for hit in STORE.finditer(part.clean, part.opening + 1, part.end):
        gap = part.clean[last:hit.start()] if last is not None else None
        if current and gap is not None and re.fullmatch(r'[\s;]*', gap):
            current.append(hit)
        else:
            if len(current) > 1:
                found.append(current)
            current = [hit]
        last = hit.end()
    if len(current) > 1:
        found.append(current)
    return found


def plain_value(part, name, value):
    """A value that stays the same between the two places: no memory read, no call, only locals and parameters."""
    if re.search(r'[*\[\]]|->|\.', value) or re.search(IDENT + r'\s*\(', value):
        return False
    for ident in set(re.findall(IDENT, value)) - KEYWORD - set(WIDTH):
        declared = re.search(r'(?:^|[;{(,])\s*(?:[A-Za-z_]\w*\s+)+\**\s*' + re.escape(ident) + r'\s*[;,=)\[]',
                             part.clean[part.clean.rfind(name, 0, part.opening):part.end])
        if not declared or _address_taken(part.body, ident):
            return False
    return True


def disjoint(first, second):
    a, b = integer(first['offset']), integer(second['offset'])
    return a + WIDTH[first['type']] <= b or b + WIDTH[second['type']] <= a


def hoists(source, part, name):
    found = []
    for run in runs(part):
        for i, first in enumerate(run):
            value = ' '.join(first['value'].split())
            if not plain_value(part, name, value):
                continue
            for j in range(i + 2, len(run)):
                twin = run[j]
                if (' '.join(twin['value'].split()) != value or twin['base'] != first['base']
                        or twin['type'] != first['type'] or not disjoint(first, twin)):
                    continue
                between = run[i + 1:j]
                if not all(m['base'] == first['base'] and disjoint(m, twin) and disjoint(m, first) for m in between):
                    continue
                text = source[twin.start():twin.end()]
                found.append(edit(source, [(twin.start(), twin.end(), ''), (first.end(), first.end(), '\n' + text)]))
    return list(dict.fromkeys(found))[:LIMIT]


def unwrap_scopes(source, name):
    """Every `do { ... } while (0);` of the function body taken off (its braces stay), as macro_one_shot_unwrap does."""
    part = view(source, name)
    if not part:
        return source
    edits = []
    for wrapper in re.finditer(r'\bdo\s*{', part.clean[part.opening:part.end]):
        opening = part.opening + wrapper.end() - 1
        end = close(part.clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', part.clean[end:]) if end else None
        if tail and not CONTROL.search(_blank(part.clean[opening + 1:end - 1])):
            edits += [(part.opening + wrapper.start(), opening, ''), (end, end + tail.end(), '')]
    return edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for moved in hoists(source, part, name):
        out.append(('twin_store_hoist', moved))
        unwrapped = unwrap_scopes(moved, name)
        if unwrapped != moved:
            out.append(('twin_store_hoist_unwrap', unwrapped))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}  # the registry: no caller wiring (registry.py)
