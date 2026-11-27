"""A word m2c named by its own address, which the target reads through the global just before it.

When a function keeps a record's address in a register and reads a later member off it (`lui; addiu $s1, %lo(gPair)`
... `lhu $a1, 2($s1)`), a draft that does not know the record names the member by its address:

    extern u16 D_80012346;                 typedef struct { unsigned char head[0x2]; u16 field; } __repair_view2_u16;
    f(D_80012346);                    ->   f(((__repair_view2_u16 *) &gPair)->field);

As a symbol of its own it gets a `lui; lhu %lo` pair at every read; the same spelled `*(u16 *)((u8 *)&gPair + 2)` is
folded back to the symbol plus 2. Only a member access keeps the record's address in a register for a loop's reads.

`asm_member_view`: offered for each `D_XXXXXXXX` scalar the source declares and the target's assembly never names,
for each global whose address a register of the target holds and is read at a non-zero offset with a load or store of
that width. The assembly does not say where the global is, so each such pair is a child and the exact judge decides.

Matched on an SN GCC 2.8.1 `-O2` N64 function that queues a page of sound ids with a volume (the same score, 1293,
with the separate symbol and with the offset cast; exact with the member).
"""
import re

from .csource import _blank, find

FAMILY = 'asm_member_view'
FAMILIES = (FAMILY,)

_KINDS = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4,
          'unsigned char': 1, 'signed char': 1, 'unsigned short': 2, 'short': 2, 'unsigned int': 4, 'int': 4}
_SPELL = {'unsigned char': 'u8', 'signed char': 's8', 'unsigned short': 'u16', 'short': 's16', 'unsigned int': 'u32',
          'int': 's32'}
_OPS = {'lbu': ('u8', 's8'), 'lb': ('s8', 'u8'), 'sb': ('u8', 's8'), 'lhu': ('u16', 's16'), 'lh': ('s16', 'u16'),
        'sh': ('u16', 's16'), 'lw': ('s32', 'u32'), 'sw': ('s32', 'u32'), 'lwc1': ('f32',), 'swc1': ('f32',)}
_BASE = re.compile(r'\baddiu\s+\$(?P<reg>\w+),\s*\$\w+,\s*%lo\((?P<symbol>[A-Za-z_]\w*)\)')
_ACCESS = re.compile(r'\b(?P<op>lbu|lb|sb|lhu|lh|sh|lw|sw|lwc1|swc1)\s+\$\w+,\s*(?P<at>0x[0-9A-Fa-f]+|\d+)\(\$(?P<reg>\w+)\)')
_WRITES = re.compile(r'(?:^|\*/)\s*(?!s[bhwd]\b|sw[lrc]|sdc|b|j)[a-z][a-z0-9.]*\s+\$(?P<reg>\w+)\s*,')
_EXTERN = re.compile(
    r'(?m)^[ \t]*extern[ \t]+(?P<type>(?:unsigned |signed )?\w+)[ \t]+(?P<name>D_[0-9A-Fa-f]{8})[ \t]*;[ \t]*\n')


def _members(asm):
    """{(symbol, offset, operation)}: reads and writes at a non-zero offset off a register holding a symbol's address."""
    held, found = {}, []
    for line in asm.splitlines():
        base = _BASE.search(line)
        if base:
            held[base['reg']] = base['symbol']
            continue
        access = _ACCESS.search(line)
        if access and access['reg'] in held and int(access['at'], 0):
            item = (held[access['reg']], int(access['at'], 0), access['op'])
            if item not in found:
                found.append(item)
        written = _WRITES.search(line)  # a register given another value no longer holds the address
        if written:
            held.pop(written['reg'], None)
    return found


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    members = _members(asm)
    if not members:
        return []
    clean = _blank(source)
    out, seen = [], set()
    for extern in _EXTERN.finditer(clean):
        symbol, kind = extern['name'], ' '.join(extern['type'].split())
        if kind not in _KINDS or re.search(rf'\b{symbol}\b', asm):
            continue
        spelled = _SPELL.get(kind, kind)
        for base, offset, op in members:
            if spelled not in _OPS[op] or offset % _KINDS[kind] or base == symbol:
                continue
            if not re.search(rf'(?m)^[ \t]*extern\b[^;()]*\b{base}\b[^;()]*;', clean):
                continue
            view = f'__repair_view{offset:X}_{spelled}'
            member = f'((({view} *)&{base})->field)'
            body = re.sub(rf'\b{symbol}\b', member, source[span[0]:span[1]])
            if body == source[span[0]:span[1]]:
                continue
            at = source.rfind('\n', 0, span[0]) + 1
            typedef = f'typedef struct {{ unsigned char head[0x{offset:X}]; {kind} field; }} {view};\n'
            text = source[:at] + typedef + source[at:span[0]] + body + source[span[1]:]
            if text not in seen:
                seen.add(text)
                out.append((FAMILY, text))
    return out[:6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
