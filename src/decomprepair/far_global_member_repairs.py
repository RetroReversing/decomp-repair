"""Globals named by their own address that the target reaches off another symbol, written as members of one struct there.

m2c names every constant address it folds, so a field deep inside a large object becomes a global of its own:

    extern short D_800B8000;                 extern struct { char pad_0[0x27000]; s16 x_27000; ... } D_80091000;
    D_800B8000 = 2;                  ->      D_80091000.x_27000 = 2;

The target never names that address. It builds the object's base (`lui`/`addiu %lo(D_80091000)`) and adds the part of the
offset that does not fit a load's displacement to it. GCC writes that form for a member of a declared object; a global
of its own is addressed by its own `%hi`/`%lo`, and a cast of the base plus a constant is folded back into the symbol
(measured with SN GCC 2.8.1: separate globals 2120, casts 2230, one struct 0, the other edits being equal).

All the moved globals of one base are written together (each alone shares no base register). Taken only when: the
target's assembly names no symbol for the moved address; some load or store of the member's width has a displacement
that agrees with its offset modulo 0x8000; the base is the nearest symbol below it whose address the target builds;
the moved globals are scalars; and the base is declared by the source (or not at all), not by the project header, and is
not used by the function itself.
"""
import re

from .csource import _blank, find

FAMILY = 'far_global_member'
FAMILIES = (FAMILY,)

SIZE = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
        'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'long': 4, 'f32': 4, 'float': 4}
ACCESS = {'lb': 1, 'lbu': 1, 'sb': 1, 'lh': 2, 'lhu': 2, 'sh': 2, 'lw': 4, 'lwu': 4, 'sw': 4, 'lwc1': 4, 'swc1': 4}
LIMIT = 0x100000  # an offset further than this is another object
_NAMED = re.compile(r'\bD_([0-9A-F]{8})\b')
_BASE = re.compile(r'\baddiu\s+\$\w+\s*,\s*\$\w+\s*,\s*%lo\(\s*(D_[0-9A-F]{8})\s*\)')
_MEMORY = re.compile(r'\b(?P<op>lbu?|sb|lhu?|sh|lwu?|sw|lwc1|swc1)\s+\$\w+\s*,\s*'
                     r'(?P<disp>\(\s*0x[0-9A-Fa-f]+\s*&\s*0xFFFF\s*\)|-?0x[0-9A-Fa-f]+|-?\d+)\s*\(\s*\$(?!sp\b)\w+\s*\)')


def _displacements(asm):
    """{(width, displacement modulo 0x8000)} of the target's loads and stores off a register other than the stack."""
    out = set()
    for m in _MEMORY.finditer(asm):
        text = m['disp']
        value = int(text.strip('( ').split('&')[0], 0) if text.startswith('(') else int(text, 0)
        out.add((ACCESS[m['op']], value % 0x8000))
    return out


def _declaration(text, symbol):
    """[(match, type, array)] of the `extern ... symbol;` lines of `text`."""
    return [(m, ' '.join(m['type'].split()), m['array'])
            for m in re.finditer(rf'(?m)^[ \t]*extern[ \t]+(?P<type>[A-Za-z_][\w \t]*?(?:[ \t]*\*)*)[ \t]*\b{symbol}\b'
                                 rf'(?P<array>[ \t]*\[[^\]\n]*\])*[ \t]*;[ \t]*\n', text)]


def _width(type_):
    return 4 if type_.endswith('*') else SIZE.get(type_.removeprefix('volatile '))


def variants(source, name, header='', asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    body = clean[opening:span[1]]
    bases = sorted({int(m[1][2:], 16) for m in _BASE.finditer(asm)})
    named = {int(a, 16) for a in _NAMED.findall(asm)}
    reached = _displacements(asm)
    hidden = _blank(header or '')
    groups = {}
    for symbol in sorted(set(m[0] for m in _NAMED.finditer(body))):
        address = int(symbol[2:], 16)
        below = [b for b in bases if b < address and address - b < LIMIT]
        if address in named or not below:
            continue
        declared = _declaration(clean, symbol) or _declaration(hidden, symbol)
        if len(declared) != 1 or declared[0][2]:
            continue
        type_ = declared[0][1]
        width, offset = _width(type_), address - below[-1]
        if not width or offset % width or (width, offset % 0x8000) not in reached:
            continue
        groups.setdefault(below[-1], []).append((offset, width, type_, symbol))
    out = []
    for base, members in sorted(groups.items()):
        symbol = f'D_{base:08X}'
        members.sort()
        if re.search(rf'\b{symbol}\b', body) or re.search(rf'\b{symbol}\b', hidden):
            continue
        declared = _declaration(clean, symbol)
        if len(re.findall(rf'\b{symbol}\b', clean)) != len(declared) or len(declared) > 1:
            continue
        fields, cursor = [], 0
        for offset, width, type_, _ in members:
            if offset < cursor:
                break
            if offset > cursor:
                fields.append(f'char pad_{cursor:X}[0x{offset - cursor:X}];')
            fields.append(f'{type_} x_{offset:X};')
            cursor = offset + width
        else:
            struct = f'extern struct {{ {" ".join(fields)} }} {symbol};\n'
            new_body = source[opening:span[1]]
            for offset, _, _, moved in members:
                for m in reversed(list(re.finditer(rf'(?<![\w.>]){moved}\b', _blank(new_body)))):
                    new_body = new_body[:m.start()] + f'{symbol}.x_{offset:X}' + new_body[m.end():]
            head = source[:opening]
            # a member's own declaration goes only when nothing else in the file names it
            for _, _, _, moved in members:
                rest = _blank(head + source[span[1]:])
                found = _declaration(rest, moved)
                if len(found) == 1 and len(re.findall(rf'\b{moved}\b', rest)) == 1:
                    head = re.sub(rf'(?m)^[ \t]*extern[ \t][^;\n]*\b{moved}[ \t]*;[ \t]*\n', '', head, count=1)
            if declared:
                head = re.sub(rf'(?m)^[ \t]*extern[ \t][^;\n]*\b{symbol}\b[^;\n]*;[ \t]*\n', lambda _, new=struct: new, head,
                              count=1)
            else:
                at = _blank(head).rfind('\n', 0, span[0]) + 1
                head = head[:at] + struct + head[at:]
            out.append((FAMILY, head + new_body + source[span[1]:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'archs': ('mips',)}
