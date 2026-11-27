"""A loop's reads through m2c's stepped cursors into a local array, written as indices by the loop counter.

The original indexed a local table of words by the counter (`x = p[i * 2]; y = p[i * 2 + 1];`) and the compiler's strength
reduction made the cursors. m2c writes them out beside the counter:

    var_t0 = sp50;            /* char *: a pointer cursor */
    var_t1 = 4;               /* s32: a byte offset */
    do {
        temp_a2 = *(s32 *)var_t0;
        temp_a1 = *(sp50 + var_t1);
        var_t2 += 1;
        var_t0 += 8;
        var_t1 += 8;
    } while (var_t2 < 3);

`*(sp50 + var_t1)` is m2c's byte offset added to the array (C would scale it a second time, so as written the draft reads
past the array). The child reads `sp50[var_t2 * 2]` and `sp50[var_t2 * 2 + 1]` and drops the cursors. On a 149-instruction
N64 triangle test (SN GCC 2.8.1 `-O2`) the compiler then built the target's own pair (one pointer stepped by 8 for `x`,
the array's address held apart and indexed by an offset starting at 4 for `y`), which neither user cursor gave. The saved
best went 2004 -> 585 (the frame union split into arrays and these reads, one child) -> 85 (`branch_polarity`) -> 0
(`merge_disjoint_temporaries`, the two argument registers' runs) (one function).

A cursor is a local set once before the loop (to a 4-, 2- or 1-byte array of the function, or to a constant byte offset),
stepped once by a constant in the loop body, and read nowhere else; the counter starts at 0 and steps by 1 in the same
loop, after the reads. One child rewrites every such cursor, then one child each. The cursors' reads are the only thing
rewritten; a candidate only: the judge decides.
"""
import re

from . import frame_view_locals
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'stepped_array_reads'
FAMILIES = (FAMILY,)
LIMIT = 6

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4}
_ARRAY = re.compile(rf'(?m)^[ \t]*(?P<type>{_ID})[ \t]+(?P<name>{_ID})\s*\[\s*{_NUM}\s*\]\s*;')
_DECL = re.compile(rf'(?m)^[ \t]*(?P<type>{_ID})(?P<stars>[ \t*]+)(?P<name>{_ID})\s*;')


def _number(text):
    return int(text, 0)


def _loops(clean, lo, hi):
    """[(body start, body end, header/condition text)] of the `do` and `for` loops with a braced body."""
    out = []
    for hit in re.finditer(r'\bdo\s*\{', clean[lo:hi]):
        opening = lo + hit.end() - 1
        end = close(clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[end:hi]) if end else None
        if tail:
            after = close(clean, end + tail.end() - 1, '(', ')')
            if after:
                out.append((lo + hit.start(), opening + 1, end - 1, clean[end + tail.end():after - 1], ''))
    for hit in re.finditer(r'\bfor\s*\(', clean[lo:hi]):
        header = close(clean, lo + hit.end() - 1, '(', ')')
        brace = re.match(r'\s*\{', clean[header:hi]) if header else None
        if not brace:
            continue
        opening = header + brace.end() - 1
        end = close(clean, opening, '{', '}')
        parts = clean[lo + hit.end():header - 1].split(';')
        if end and len(parts) == 3:
            out.append((lo + hit.start(), opening + 1, end - 1, parts[1], parts[2]))
    return out


def _step(name):
    return re.compile(rf'(?<![\w.>])(?:{name}\s*\+=\s*(?P<by>{_NUM})\s*;|{name}\s*\+\+\s*;|\+\+\s*{name}\s*;|'
                      rf'{name}\s*=\s*{name}\s*\+\s*(?P<add>{_NUM})\s*;)')


def _removal(clean, a, b):
    """The span of a statement with its whole line when nothing else is on it."""
    line = clean.rfind('\n', 0, a) + 1
    tail = re.match(r'[ \t]*\n', clean[b:])
    return (line, b + tail.end()) if not clean[line:a].strip() and tail else (a, b)


def _counter(clean, lo, loop):
    """(name, position of its step in the body or the body's end) of a counter from 0 by 1, or None."""
    start, body, body_end, condition, header = loop
    test = re.match(rf'\s*(?:\(\s*\w+\s*\)\s*)?(?P<name>{_ID})\s*<', condition)
    if not test:
        return None
    name = test['name']
    inits = list(re.finditer(rf'(?<![\w.>]){name}\s*=\s*(?P<value>[^;=(){{}}]+);', clean[lo:body]))
    if not inits or inits[-1]['value'].strip() != '0':
        return None
    steps = list(_step(name).finditer(clean, body, body_end))
    in_header = re.fullmatch(rf'\s*(?:{name}\s*\+\+|\+\+\s*{name}|{name}\s*\+=\s*1)\s*', header)
    if in_header:
        return (name, body_end) if not steps else None
    if len(steps) != 1 or (steps[0]['by'] or steps[0]['add'] or '1') != '1':
        return None
    if re.search(r'\bcontinue\b', clean[body:body_end]):
        return None
    return name, steps[0].start()


def _element(source_type, arrays, base):
    return _SIZES.get(arrays.get(base, source_type))


def _cursor(clean, part, loop, counter, name, arrays, pointees):
    """The edits that write `name`'s reads as indices, or None."""
    start, body, body_end, _, _ = loop
    steps = list(_step(name).finditer(clean, body, body_end))
    if len(steps) != 1 or name == counter[0]:
        return None
    inits = list(re.finditer(rf'(?<![\w.>]){name}\s*=(?!=)\s*(?P<value>[^;{{}}]+);', clean[part.opening:start]))
    writes = re.findall(rf'(?<![\w.>]){name}\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{name}\b',
                        clean[part.opening:part.end])
    if len(inits) != 1 or len(writes) != 2:
        return None
    init, step = inits[0], steps[0]
    # the size one step moves: a pointer cursor scales by its pointee, an integer offset is in bytes
    stride = _number(step['by'] or step['add'] or '1') * pointees.get(name, 1)
    value = init['value'].strip()
    pointer = re.fullmatch(rf'&?\s*(?P<base>{_ID})(?:\s*\[\s*0\s*\])?', value)
    offset = re.fullmatch(_NUM, value)
    reads = []
    if pointer and pointer['base'] in arrays and name in pointees:
        base, first = pointer['base'], 0
        for hit in re.finditer(rf'\*\s*\(\s*(?P<type>{_ID})\s*\*\s*\)\s*{name}\b', clean[body:body_end]):
            reads.append((body + hit.start(), body + hit.end(), base, hit['type']))
    elif offset and name not in pointees:
        first = _number(value)
        for hit in re.finditer(rf'\*\s*\(\s*(?P<type>{_ID})\s*\*\s*\)\s*\(\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*'
                               rf'(?P<base>{_ID})\s*\+\s*{name}\s*\)|\*\s*\(\s*(?P<plain>{_ID})\s*\+\s*{name}\s*\)',
                               clean[body:body_end]):
            base = hit['base'] or hit['plain']
            if base in arrays:
                reads.append((body + hit.start(), body + hit.end(), base, hit['type'] or arrays[base]))
    else:
        return None
    if not reads:
        return None
    mentions = [m for m in re.finditer(rf'(?<![\w.>]){name}\b', clean[part.opening:part.end])]
    # the declaration, the initialisation, the step (once or twice named) and the reads: nothing else
    named_in_step = len(re.findall(rf'(?<![\w.>]){name}\b', step.group()))
    if len(mentions) != 2 + named_in_step + len(reads):
        return None
    edits = []
    for a, b, base, kind in reads:
        size = _SIZES.get(arrays[base])
        if not size or _SIZES.get(kind) != size or stride % size or first % size or stride < size:
            return None
        if a > step.start() or a > counter[1] or re.match(r'\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)', clean[b:]):
            return None
        scale, ahead = stride // size, first // size
        index = counter[0] if scale == 1 else f'{counter[0]} * {scale}'
        if ahead:
            index += f' + {ahead}'
        read = f'{base}[{index}]'
        if kind != arrays[base]:
            read = f'(({kind}) {read})'
        edits.append((a, b, read))
    for hit in (step,):
        edits.append((*_removal(clean, hit.start(), hit.end()), ''))
    a = part.opening + init.start()
    edits.append((*_removal(clean, a, part.opening + init.end()), ''))
    return edits


def variants(source, name):
    out = _reads(source, name)
    if 'm2c_initial_frame' in source:
        # the table is still views of m2c's frame union: split it and rewrite the reads in one child, since the split
        # alone scores no better (2004 -> 2004; both together 585 on the function above)
        for _, split in frame_view_locals.variants(source, name):
            out += _reads(split, name)[:1]
    return list(dict.fromkeys(out))[:LIMIT]


def _reads(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening, part.end
    arrays = {m['name']: m['type'] for m in _ARRAY.finditer(clean, lo, hi) if m['type'] in _SIZES}
    if not arrays:
        return []
    pointees, declared = {}, []
    for hit in _DECL.finditer(clean, lo, hi):
        stars = hit['stars'].count('*')
        if stars == 1 and hit['type'] in _SIZES:
            pointees[hit['name']] = _SIZES[hit['type']]
        if hit['type'] in _SIZES and (stars == 1 or stars == 0):
            declared.append(hit['name'])
    found = []
    for loop in _loops(clean, lo, hi):
        counter = _counter(clean, lo, loop)
        if not counter:
            continue
        for cursor in declared:
            edits = _cursor(clean, part, loop, counter, cursor, arrays, pointees)
            if edits:
                found.append(edits)
    if not found:
        return []
    groups = [[change for edits in found for change in edits]]
    if len(found) > 1:
        groups += found[:LIMIT - 1]
    out = []
    for changes in groups:
        text = edit(source, changes)
        if text != source:
            out.append((FAMILY, text))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60, 'archs': ('mips',)}
