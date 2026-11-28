"""Commute a bounded signed row offset with its 32-bit MIPS address.

For one linked KMC O1 state handler, spelling `row[index]` as a signed byte
index times the row stride plus the 32-bit base improved the diagnostic from
755 to 750. The compiler's allocation reason is not established.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'commute_signed_row_address'
LIMIT = 4


def variants(source, name, header='', flags=None):
    flags = flags.split() if isinstance(flags, str) else list(flags or ())
    if ('-mgp32' not in flags or any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@', '-mgp64'))
                                    or (f.startswith('-mabi') and f not in ('-mabi=32', '-mabi=o32')) for f in flags)):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    if any(integer_abi.scalar(t, context, 'mips') != expected for t, expected in
           (('s8', (8, True)), ('u16', (16, False)), ('u32', (32, False)))):
        return []
    part = view(source, name)
    if not part:
        return []
    clean, body = part.clean, part.body
    if re.search(r'\b(?:volatile|_Atomic|typedef)\b|\bgoto\s*\*', body):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    type_shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*)(?:s8|u16|u32)\s*(?=[;=,\[])'
    type_typeof = r'\b(?:__typeof__|typeof)\s*\([^;{}]*\)\s*\**\s*(?:s8|u16|u32)\s*(?=[;=,\[])'
    if {'s8', 'u16', 'u32'} & macros or re.search(type_shadow, body) or re.search(type_typeof, body):
        return []
    pattern = re.compile(rf'(?m)^[ \t]*(?P<stmt>(?P<dst>{IDENT})\s*=\s*(?P<row>{IDENT})\s*\[\s*(?P<idx>{IDENT})\s*\]\s*;)')
    result = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        dst, row, idx = (hit[k] for k in ('dst', 'row', 'idx'))
        if len({dst, row, idx}) != 3 or {dst, row, idx} & macros:
            continue
        if clean[part.opening + 1:hit.start('stmt')].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        decls = []
        for var, pat in ((dst, rf'u16\s*\*\s*(?P<n>{re.escape(dst)})\s*;'),
                         (row, rf'u16\s*\(\s*\*\s*(?P<n>{re.escape(row)})\s*\)\s*\[\s*(?P<w>[1-9][0-9]*)\s*\]\s*;'),
                         (idx, rf's8\s+(?P<n>{re.escape(idx)})\s*;')):
            found = list(re.finditer(rf'(?m)^[ \t]*{pat}', body))
            if len(found) != 1:
                break
            pos = part.opening + 1 + found[0].start('n')
            shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])'
            typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(var)}\s*(?=[;=,\[])'
            multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*{re.escape(var)}\s*(?:[;=,\[])'
            expected = 0 if var == row else 1
            if (re.search(multi, body) or any(part.opening < a < pos < b for a, b in pairs.items())
                    or len(re.findall(shadow, body)) != expected or re.search(typeof_shadow, body)):
                break
            decls.append(found[0])
        else:
            stride = int(decls[1]['w']) * 2
            if stride > 0x7fffffff // 128:
                continue
            replacement = f'{dst} = (u16 *)(({idx} * {stride}) + (u32){row});'
            result.append((FAMILY, edit(source, [(hit.start('stmt'), hit.end('stmt'), replacement)])))
            if len(result) >= LIMIT:
                break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
