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

The width is read off the target's own loads; the exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY = 'asm_symbol_read_width'
FAMILY_CAST = 'float_literal_int_cast'
FAMILY_OFFSET = 'asm_offset_read_width'
FAMILIES = (FAMILY, FAMILY_OFFSET, FAMILY_CAST)
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
