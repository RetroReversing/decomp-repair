"""Reads of a table symbol written at the width and signedness the target loads it with.

m2c and later searches leave table reads at a guessed width: `*((u16 *) (D_80109688 + i * 4))` where the target loads
`lw $a1, %lo(D_80109688)($a1)`, `*((u16 *) (D_800C46FC + i * 0xE8)) & 4` where it loads a word, and a search's identity
wrapper `__repair_inline(*((u16 *) (D_800C46A0 + o)))` (an `s8` helper over a halfword read: `lb` of the next byte)
where the target has `lb $v1, %lo(D_800C46A0)($v1)`. Each is a different load and moves the registers around it; on a
1300-instruction KMC GCC 2.7.2 controller routine the three were 10695 -> 9925 -> 9840 of its first steps (370 and
400 points), and no family read the load's width off the target.

asm_symbol_read_width
    For each symbol the target loads with one width only (`lb`/`lbu`/`lh`/`lhu`/`lw` of `%lo(SYM)`), every read
    `*((T *) (SYM + ...))` of another integer type is written with the target's type (`s8`/`u8`/`s16`/`u16`/`s32`), and an
    identity helper call around such a read (`static` one-parameter function returning its parameter) is dropped. All
    the symbols together first, then each alone.

asm_offset_read_width
    The same for a record member read as symbol plus constant offset, which m2c spells through its unknown type:
    `*((M2C_UNK *)((s8 *)&SYM + 0x210A + o))` where the target has `lh ..., %lo(SYM+0x210A)`, or `*(f32 *)(...)` over a
    halfword the target loads and converts (`lh; mtc1; cvt.s.w`): that one becomes `(f32) *(s16 *)(...)`. Every offset
    together, then each alone. A KMC GCC 2.7.2 display list builder's machine draft went 1210 -> 0 on it.

float_literal_int_cast
    `(int) 0.0002f` (a float literal cast to `int`, which is 0) written as the literal, the way a search's cast
    scaffolding comes out of `-((int) 0.0002f)`: the target compares with `-0.0002f` (`lui $at, 0xb951`).

asm_address_read_width
    A table whose address the target keeps in a register (`lui; addiu %lo(SYM)`, `addu` with an index, `lbu 0($v0)`)
    has no `%lo` load to read a width off, and m2c reads it through its unknown type, as a word, anywhere in the
    address: `*(s32 *)((i * 0x10) + D_800C0784 + k)`, `*((s32 *)((s8 *)D_800C0000 + (i * 2)))`. The width is followed
    through the register, `%lo` loads count too, and every word read whose address names one such symbol (outside a
    nested read) is written with it: all the symbols together first, then each alone. An N64 game's m2c draft of a
    three-table copy needed it before `linear_subscript_view` could make it exact.

The width is read off the target's own loads; the exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY = 'asm_symbol_read_width'
FAMILY_CAST = 'float_literal_int_cast'
FAMILY_OFFSET = 'asm_offset_read_width'
FAMILY_ADDRESS = 'asm_address_read_width'
FAMILIES = (FAMILY, FAMILY_OFFSET, FAMILY_CAST, FAMILY_ADDRESS)
LIMIT = 8
_TYPE = {'lb': 's8', 'lbu': 'u8', 'lh': 's16', 'lhu': 'u16', 'lw': 's32'}
_INTEGER = r'(?:[su](?:8|16|32)|int|short|char|unsigned\s+(?:int|short|char))'


def _widths(asm):
    found = {}
    for op, sym in re.findall(r'\b(lbu|lb|lhu|lh|lw)\s+\$\w+\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)', asm or ''):
        found.setdefault(sym, set()).add(op)
    return {sym: _TYPE[ops.pop()] for sym, ops in found.items() if len(ops) == 1}


def _identity_helpers(source):
    return {m[1] for m in re.finditer(
        r'\bstatic\s+(?:inline\s+)?[\w ]+?\b([A-Za-z_]\w*)\s*\(\s*[\w ]+?\b([A-Za-z_]\w*)\s*\)\s*\{\s*return\s+\2\s*;\s*\}',
        source)} | {m[1] for m in re.finditer(
        r'\binline\s+static\s+[\w ]+?\b([A-Za-z_]\w*)\s*\(\s*[\w ]+?\b([A-Za-z_]\w*)\s*\)\s*\{\s*return\s+\2\s*;\s*\}',
        source)}


def _edits(source, name, sym, kind, helpers):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    edits = []
    read = re.compile(rf'\*\s*\(\s*\(\s*(?P<t>{_INTEGER})\s*\*\s*\)\s*\(\s*{re.escape(sym)}\s*\+')
    for hit in read.finditer(clean, span[0], span[1]):
        depth, end = 0, None
        start = hit.start()
        for index in range(clean.index('(', start), len(clean)):
            depth += (clean[index] == '(') - (clean[index] == ')')
            if depth == 0:
                end = index + 1
                break
        if end is None:
            continue
        text = source[start:end]
        new = text[:hit.start('t') - start] + kind + text[hit.end('t') - start:]
        wrap = None
        for helper in helpers:
            before = re.search(rf'\b{re.escape(helper)}\s*\(\s*$', clean[:start])
            if before and re.match(r'\s*\)', clean[end:]):
                wrap = (before.start(), end + re.match(r'\s*\)', clean[end:]).end())
        if wrap:
            edits.append((wrap[0], wrap[1], new))
        elif hit['t'] != kind:
            edits.append((start, end, new))
    return edits


def _offset_widths(asm):
    found = {}
    for op, sym, off in re.findall(
            r'\b(lbu|lb|lhu|lh|lw)\s+\$\w+\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\+\s*(0x[0-9A-Fa-f]+|\d+)\s*\)', asm or ''):
        found.setdefault((sym, int(off, 0)), set()).add(op)
    return {key: _TYPE[ops.pop()] for key, ops in found.items() if len(ops) == 1}


def _offset_edits(source, name, widths):
    """{(symbol, offset): edits} for the dereferences of `(s8 *)&symbol + offset` in the function."""
    span = find(source, name)
    if not span:
        return {}
    clean = _blank(source)
    read = re.compile(
        r'\*\s*(?:\(\s*(?P<outer>\w+)\s*\*\s*\)\s*)?\(\s*(?:\(\s*(?P<inner>\w+)\s*\*\s*\)\s*\(\s*)?'
        r'\(\s*(?:s8|u8|char)\s*\*\s*\)\s*&\s*(?P<sym>[A-Za-z_]\w*)\s*\+\s*(?P<off>0x[0-9A-Fa-f]+|\d+)\b')
    found = {}
    for hit in read.finditer(clean, span[0], span[1]):
        key = (hit['sym'], int(hit['off'], 0))
        kind, group = widths.get(key), 'outer' if hit['outer'] else 'inner'
        if not kind or not hit[group] or hit[group] == kind:
            continue
        if hit[group] in ('f32', 'float'):
            edit = [(hit.start(), hit.start(), '(f32) '), (*hit.span(group), kind)]
        elif hit[group] == 'M2C_UNK' or re.fullmatch(_INTEGER, hit[group]):
            edit = [(*hit.span(group), kind)]
        else:
            continue
        found.setdefault(key, []).extend(edit)
    return found


def _address_widths(asm):
    """{symbol: type} for symbols every load reads one way, through `%lo(SYM)` or a register made from its address."""
    found, held = {}, {}
    for line in (asm or '').splitlines():
        text = re.sub(r'/\*.*?\*/', '', line).strip()
        load = re.match(r'(lbu|lb|lhu|lh|lw)\s+(\$\w+)\s*,\s*(.*)\((\$\w+)\)', text)
        if load:
            direct = re.fullmatch(r'%lo\(\s*([A-Za-z_]\w*)\s*\)', load[3].strip())
            sym = direct[1] if direct else held.get(load[4])
            if sym:
                found.setdefault(sym, set()).add(load[1])
            held.pop(load[2], None)
            continue
        made = re.match(r'addiu\s+(\$\w+)\s*,\s*\$\w+\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)', text)
        if made:
            held[made[1]] = made[2]
            continue
        added = re.match(r'addu\s+(\$\w+)\s*,\s*(\$\w+)\s*,\s*(\$\w+)', text)
        if added:
            sym = held.get(added[2]) or held.get(added[3])
            held.pop(added[1], None)
            if sym:
                held[added[1]] = sym
            continue
        written = re.match(r'(?!s[bhw]\b|b|j)[a-z][\w.]*\s+(\$\w+)\s*,', text)
        if written:
            held.pop(written[1], None)
    return {sym: _TYPE[next(iter(ops))] for sym, ops in found.items() if len(ops) == 1}


def _closing(text, start):
    depth = 0
    for index in range(start, len(text)):
        depth += (text[index] == '(') - (text[index] == ')')
        if depth == 0:
            return index + 1
    return None


def _without_nested_reads(text):
    """The address expression with the reads inside it (`*(T *)(...)`, `M2C_FIELD(...)`) taken out."""
    while True:
        hit = re.search(r'\*\s*\(\s*\(?\s*\w+\s*\*+\s*\)|\bM2C_FIELD\s*(?=\()', text)
        if not hit:
            return text
        start = hit.end()
        if text[hit.start()] == '*':
            start = text.index('(', hit.start())
            if not re.match(r'\(\s*\w+\s*\*+\s*\)', text[start:]):
                end = _closing(text, start)
            else:
                after = _closing(text, start)
                opening = re.compile(r'\s*\(').match(text, after)
                end = _closing(text, opening.end() - 1) if opening else after
        else:
            end = _closing(text, text.index('(', start))
        if end is None:
            return text[:hit.start()]
        text = text[:hit.start()] + ' ' + text[end:]


def _address_edits(source, name, widths):
    """{symbol: edits} for the word reads whose address names that symbol alone."""
    span = find(source, name)
    if not span:
        return {}
    clean = _blank(source)
    found = {}
    read = re.compile(r'\*\s*(?:\(\s*)?\(\s*(?P<t>s32|u32|int|M2C_UNK)\s*\*\s*\)\s*(?=\()')
    for hit in read.finditer(clean, span[0], span[1]):
        end = _closing(clean, hit.end())
        if end is None:
            continue
        address = _without_nested_reads(clean[hit.end():end])
        named = [sym for sym in widths if re.search(rf'(?<![\w.>]){re.escape(sym)}\b', address)]
        if len(named) == 1 and widths[named[0]] != 's32':
            found.setdefault(named[0], []).append((*hit.span('t'), widths[named[0]]))
    return found


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name, asm=''):
    out = []
    widths = _widths(asm)
    helpers = _identity_helpers(source)
    per = [(sym, _edits(source, name, sym, kind, helpers)) for sym, kind in sorted(widths.items())]
    per = [(sym, edits) for sym, edits in per if edits]
    if len(per) > 1:
        out.append((FAMILY, _apply(source, [e for _, edits in per for e in edits])))
    for _, edits in per:
        out.append((FAMILY, _apply(source, edits)))
    offsets = _offset_edits(source, name, _offset_widths(asm))
    if len(offsets) > 1:
        out.append((FAMILY_OFFSET, _apply(source, [e for edits in offsets.values() for e in edits])))
    out += [(FAMILY_OFFSET, _apply(source, edits)) for _, edits in sorted(offsets.items())]
    address = _address_edits(source, name, _address_widths(asm))
    if len(address) > 1:
        out.append((FAMILY_ADDRESS, _apply(source, [e for edits in address.values() for e in edits])))
    out += [(FAMILY_ADDRESS, _apply(source, edits)) for _, edits in sorted(address.items())]
    span = find(source, name)
    if span:
        clean = _blank(source)
        casts = [(m.start(), m.end(), m['lit']) for m in
                 re.finditer(r'\(\s*int\s*\)\s*(?P<lit>\d+\.\d*(?:[eE][-+]?\d+)?[fF])', clean[:span[1]]) if m.start() >= span[0]]
        if casts:
            out.append((FAMILY_CAST, _apply(source, casts)))
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
