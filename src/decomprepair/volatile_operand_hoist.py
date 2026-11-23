"""A volatile read held in a local ahead of the assignment of the operand it is added to.

A call argument that adds a volatile read to a local that the statement before it just set,

    off = base - 0x109;
    format(dst, src, scaled(base) + off);        /* scaled(): an inline that reads *base, a volatile byte */

has the volatile `lbu` emitted after the `off` and after the call's other argument moves. gcc 2.7's first scheduler orders
insns of equal priority by their position in the source, and a volatile load stays behind everything the call already did,
so the move of the first argument ends up in front of the `lbu`; the game has it behind (the `lbu` was written first). The
read in a local of its own, assigned before the neighbouring assignment (`mult = scaled(base); off = base - 0x109;
format(dst, src, mult + off);`), puts the `lbu` first in the source and so first in the equal-priority order: 60 -> 0 on a
578-instruction menu routine (`gcc-2.7.2-kmc -O2 -G0 -mips3 -mgp32 -mfp32`). `temporary_hoist` leaves it alone: it holds
only operands free of calls and `volatile` names.

Offered only where moving the read is the same program: the statement before the call is one plain assignment whose
right-hand side reads no `volatile` object (a pointer to one used as a value is no read) and calls nothing, so the read crosses nothing that can observe it; the read
is a call of an inline function of this source, whose arguments are plain names of locals declared `volatile`, added to
(or subtracted from) the local that assignment sets, in the next statement, a call; and the inline function's return type
is a word type the local can have.

`variants` gives, labelled `volatile_operand_hoist`, one child per such pair.
"""
import re

from .case_temporary_repairs import _identifiers
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'volatile_operand_hoist'
FAMILIES = (FAMILY,)
LIMIT = 6
ID = r'[A-Za-z_]\w*'
PAIR = re.compile(
    rf'(?P<indent>[ \t]*)(?P<local>{ID})\s*=(?!=)\s*(?P<rhs>[^;{{}}]+);[ \t]*\n(?P<gap>[ \t]*)(?P<call>{ID})\s*\((?P<args>[^;{{}}]*)\)\s*;')
WORD = ('int', 's32', 'u32', 'unsigned int', 'u16', 's16', 'long')


def _inline_types(text):
    out = {}
    for m in re.finditer(rf'(?:static\s+inline|inline\s+static|inline)\s+([A-Za-z_][\w ]*?\*?)\s*({ID})\s*\(', _blank(text)):
        out[m[2]] = re.sub(r'\s+', ' ', m[1]).strip()
    return out


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    inlines = _inline_types(header + '\n' + source[:span[0]])
    volatile_names = set()
    for m in re.finditer(rf'(?m)^[ \t]*[^;(){{}}\n]*\bvolatile\b[^;(){{}}\n]*?({ID})\s*;', clean[opening:end]):
        volatile_names.add(m[1])
    if not inlines or not volatile_names:
        return []
    taken = _identifiers(source)
    out = []
    for hit in PAIR.finditer(clean, opening, end):
        if hit['call'] in ('if', 'while', 'for', 'return', 'switch'):
            continue
        if re.search(rf'\b{ID}\s*\(', hit['rhs']):
            continue  # (a call on the right: it may do anything)
        if re.search(r'\bvolatile\b', hit['rhs']) or any(re.search(rf'\*\s*{v}\b|\b{v}\s*(?:\[|->|\.)', hit['rhs']) for v in volatile_names):
            continue
        local = hit['local']
        found = None
        for m in re.finditer(rf'(?P<x>(?P<fn>{ID})\s*\(\s*(?P<arg>{ID})\s*\))\s*(?P<op>[-+])\s*{re.escape(local)}\b', hit['args']):
            if m['fn'] in inlines and m['arg'] in volatile_names and inlines[m['fn']] in WORD:
                found = m
                break
        if not found:
            continue
        fresh = '__repair_volatile_read'
        while fresh in taken:
            fresh += '_'
        kind = inlines[found['fn']]
        args_start = hit.start('args')
        call_args = source[args_start:hit.end('args')]
        new_args = call_args.replace(found['x'], fresh, 1)
        text = (source[:hit.start()] + f"{hit['indent']}{fresh} = {found['x']};\n" + source[hit.start():args_start]
                + new_args + source[hit.end('args'):])
        text = text[:opening + 1] + f"\n  {kind} {fresh};" + text[opening + 1:]
        if text != source and all(text != t for _, t in out):
            out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 65}
