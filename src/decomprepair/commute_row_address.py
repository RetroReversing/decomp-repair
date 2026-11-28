"""Commute a bounded row offset with a 32-bit MIPS table address.

A KMC O1 state handler used an unsigned byte times a row stride to form a
byte-table pointer. Expressing the address as offset plus the table's 32-bit
address reduced the linked diagnostic from 150 to 145. Allocation remains a
hypothesis; the judge decides whether this form helps another function.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'commute_row_address'
LIMIT = 6


def variants(source, name, header='', flags=None):
    flags = flags.split() if isinstance(flags, str) else list(flags or ())
    if ('-mgp32' not in flags or any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@', '-mgp64'))
                                    or (f.startswith('-mabi') and f not in ('-mabi=32', '-mabi=o32')) for f in flags)):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic|asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    if any(integer_abi.scalar(t, context, 'mips') != expected for t, expected in
           (('u8', (8, False)), ('u32', (32, False)), ('s32', (32, True)))):
        return []
    part = view(source, name)
    if not part:
        return []
    clean, body = part.clean, part.body
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    if (re.search(r'\btypedef\b', body) or macros.intersection(re.findall(IDENT, body)) or {'u8', 'u32', 's32'} & macros
            or re.search(rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*)(?:u8|u32)\s*(?=[;=,\[])', body)
            or re.search(r'\b(?:__typeof__|typeof)\s*\([^;{}]*\)\s*\**\s*(?:u8|u32)\s*(?=[;=,\[])', body)):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    pattern = re.compile(
        rf'(?m)^[ \t]*(?P<offset>{IDENT})\s*=\s*(?P<index>{IDENT})\s*\*\s*(?P<stride>0[xX][0-9A-Fa-f]+|[0-9]+)\s*;'
        rf'\s*\n[ \t]*(?P<statement>(?P<row>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*(?P=offset)\s*;)')
    out = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        offset, index, row, base = (hit[k] for k in ('offset', 'index', 'row', 'base'))
        literal = hit['stride']
        if len(literal) > 1 and literal.startswith('0') and not literal.lower().startswith('0x'):
            continue  # C's leading-zero octal is deliberately not interpreted here.
        if len({offset, index, row, base}) != 4 or int(literal, 0) > 0x7fffffff // 255:
            continue
        if clean[part.opening + 1:hit.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        for var, typ, star in ((offset, 's32', ''), (index, 'u8', ''), (row, 'u8', r'\*'), (base, 'u8', r'\*')):
            decls = list(re.finditer(rf'(?m)^[ \t]*{typ}\s*{star}\s*(?P<name>{re.escape(var)})\s*;', body))
            if len(decls) != 1:
                break
            position = part.opening + 1 + decls[0].start('name')
            if any(part.opening < a < position < b for a, b in pairs.items()):
                break
            shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])'
            typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(var)}\s*(?=[;=,\[])'
            if len(re.findall(shadow, body)) != 1 or re.search(typeof_shadow, body):
                break
        else:
            replacement = f'{row} = (u8 *)({offset} + (u32){base});'
            out.append((FAMILY, edit(source, [(hit.start('statement'), hit.end('statement'), replacement)])))
            if len(out) >= LIMIT:
                break
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
