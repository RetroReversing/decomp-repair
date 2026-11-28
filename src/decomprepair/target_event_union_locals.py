"""Rebuild a target-proved event with split word and byte payloads.

An N64 audio dispatcher passed several separately guessed stack locals as one
record. The target stores a halfword at the record base, a pointer at +4, a
word at +8 and a channel byte at +12; another event writes bytes at +8..+10.
Combining the target-witnessed aliases into a typed record improved one KMC O2
judge from 17198 to 15661. This repairs an incomplete draft, not an equivalence
claim about independent locals: the target stores establish the layout.
"""
import re

from .integer_repair_support import edit, view
from .target_stack_event_record import target_bases

FAMILY = 'target_event_union_locals'


def variants(source, name, asm, header=''):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:__LINE__|__COUNTER__)\b', context)
            or re.search(r'\bvolatile\b', part.body)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|s32|u8)\s*;', context)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:s16|s32|u8|type|pad|ptr|data|value|bytes|chan)\b', context)):
        return []
    result = []
    for base in target_bases(asm):
        if base != 0x20:  # these aliases are byte offsets in the original stack frame
            continue
        aliases = {'sp20': ('s32', 'type'), 'sp24': (r'void\s*\*', 'ptr'),
                   'sp28': ('s32', 'data.value'), 'sp2C': ('u8', 'chan'),
                   'unksp29': ('s32', 'data.bytes[1]'), 'unksp2A': ('s32', 'data.bytes[2]'),
                   'sp24_a1': (r'void\s*\*', 'ptr'), 'sp24_a2': (r'void\s*\*', 'ptr'),
                   'sp28_a1': ('s32', 'data.value'), 'sp28_a2': ('s32', 'data.value'),
                   'sp28_a3': ('s32', 'data.bytes[0]'), 'sp2C_a1': ('u8', 'chan')}
        if any(re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(n) + r'\b', context) for n in aliases):
            continue
        declarations = []
        for local, (kind, _) in aliases.items():
            found = list(re.finditer(r'(?m)^[ \t]*' + kind + r'\s*' + re.escape(local) + r'\s*;[^\n]*\n', source[part.opening:part.end]))
            if len(found) != 1:
                break
            declarations.append((part.opening + found[0].start(), part.opening + found[0].end()))
        if len(declarations) != len(aliases):
            continue
        if len(re.findall(r'\balEvtqPostEvent\s*\([^;{}]*&\s*sp20\b[^;{}]*\)', part.body)) != 4:
            continue
        if len(re.findall(r'&\s*sp20\b', part.body)) != 4:
            continue
        decl_start, decl_end = declarations[0]
        refs = re.finditer(r'\bsp20\b', part.clean[part.opening:part.end])
        if any(not (decl_start <= part.opening + ref.start() < decl_end
                    or re.search(r'&\s*$', part.clean[part.opening:part.opening + ref.start()])
                    or re.match(r'\s*=\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*;', part.clean[part.opening + ref.end():part.end]))
               for ref in refs):
            continue
        # Each other alias is only assigned; no independent address or later read may be lost.
        if any(re.search(r'\b' + re.escape(n) + r'\b(?!\s*=)', re.sub(r'(?m)^\s*[^\n;]*\b' + re.escape(n) + r'\s*;[^\n]*$', '', part.body))
               for n in aliases if n != 'sp20'):
            continue
        for off in (base + 8, base + 9, base + 10):
            if not re.search(r'\bsb\s+\$\w+\s*,\s*(?:0x' + format(off, 'X') + '|' + str(off) + r')\(\$sp\)', asm or '', re.I):
                break
        else:
            fresh = '__repair_event'
            if re.search(r'\b' + fresh + r'\b', context):
                continue
            changes = [(a, b, '') for a, b in declarations]
            changes.append((part.opening + 1, part.opening + 1,
                            '\n    struct { s16 type; s16 pad; void *ptr; union { s32 value; u8 bytes[4]; } data; u8 chan; } '
                            + fresh + ';'))
            for local, (_, field) in aliases.items():
                for ref in re.finditer(r'\b' + re.escape(local) + r'\b', part.clean[part.opening:part.end]):
                    start = part.opening + ref.start()
                    if any(a <= start < b for a, b in declarations):
                        continue
                    changes.append((start, start + len(local), fresh + '.' + field))
            result.append((FAMILY, edit(source, changes)))
    return result[:4]


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
