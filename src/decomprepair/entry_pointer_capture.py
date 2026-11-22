"""Stage a frame pointer around the intervening signed-byte entry load."""

import re

from .goto_structure_repairs import parse
from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions

FAMILY = 'entry_pointer_capture'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9]\d*)'
_BLOCK = re.compile(r'\bdo\s*{(?P<body>[^;{}]+;\s*[^;{}]+;\s*[^;{}]+;)\s*}\s*while\s*\(\s*0\s*\)\s*;')
_POINTER = re.compile(rf'({IDENT}(?:\.{IDENT})?)=\*void\*\*char\*({IDENT})\+({_NUMBER})')
_BYTE = re.compile(rf'({IDENT})=({IDENT})char\*({IDENT}),({_NUMBER})')
_GUARD = re.compile(rf'\s*if\s*\(\s*(?P<mode>{IDENT})\s*==\s*0\s*\)')


def _short(text):
    return re.sub(r'[\s()]', '', text)


def _target(asm, early, late, offset, mode):
    rows = instructions(asm)[:42]
    load = r'lw\s+(\$\w+),\s*{}\((\$\w+)\)'
    for index in range(len(rows)-5):
        a, b, mode_high, mode_low, spill, slot = rows[index:index+6]
        first = re.fullmatch(load.format(early), a)
        second = re.fullmatch(load.format(late), b)
        high = re.fullmatch(rf'lui\s+(\$\w+),\s*%hi\({mode}\)', mode_high)
        if not first or not second or not high or first[2] != second[2]:
            continue
        mode_reg, pointer_reg, actor_reg = map(re.escape, (high[1], first[1], second[1]))
        if (re.fullmatch(rf'lb\s+{mode_reg},\s*%lo\({mode}\)\({mode_reg}\)', mode_low)
                and re.fullmatch(rf'sw\s+{pointer_reg},\s*{_NUMBER}\(\$sp\)', spill)
                and re.fullmatch(rf'lb\s+\$\w+,\s*{offset}\({actor_reg}\)', slot)):
            return True
    return False


def variants(source, name, asm):
    part = view(source, name) if asm and '%hi' in asm and 'lb' in asm else None
    if not part:
        return []
    block = _BLOCK.search(part.clean, part.opening, part.end)
    if not block or not (guard := _GUARD.match(part.clean, block.end(), part.end)):
        return []
    try:
        preceding = parse(part.clean, part.opening+1, block.start())
    except ValueError:
        return []
    if any(stmt.kind != 'simple' or re.search(r'[=(]', part.clean[stmt.start:stmt.end]) for stmt in preceding):
        return []
    first, second, slot, _ = block['body'].split(';')
    pointer = _POINTER.fullmatch(_short(first))
    actor = _POINTER.fullmatch(_short(second))
    byte = _BYTE.fullmatch(_short(slot))
    if not pointer or not actor or not byte or '.' not in pointer[1]:
        return []
    if pointer[2] != actor[2] or actor[1] != byte[3]:
        return []
    frame, member = pointer[1].split('.')
    declarations = part.clean[part.opening+1:block.start()]
    aggregate = re.search(rf'\bstruct\s*{{([^{{}}]+)}}\s*{frame}\s*;', declarations)
    if not aggregate or not re.search(rf'\bvoid\s*\*\s*{member}\s*;', aggregate[1]):
        return []
    mode = guard['mode']
    prelude = part.clean[:part.opening]
    if not re.search(rf'\bextern\s+(?:s8|signed\s+char)\s+{mode}\s*;', prelude):
        return []
    helper = re.search(rf'\b(?:s8|signed\s+char)\s+{byte[2]}\s*\(\s*char\s*\*\s*({IDENT})\s*,'
                       rf'\s*(?:s32|int)\s+({IDENT})\s*\)\s*{{\s*return\s+([^;]+);\s*}}', prelude)
    if not helper or _short(helper[3]) not in {f'*{kind}*{helper[1]}+{helper[2]}'
                                               for kind in ('s8', 'signedchar')}:
        return []
    if not _target(asm, pointer[3].lower(), actor[3].lower(), byte[4].lower(), mode):
        return []
    names = ['entry_road', 'entry_mode']
    for index, fresh in enumerate(names):
        while re.search(rf'\b{fresh}\b', part.clean):
            fresh += '_'
        names[index] = fresh
    capture, selected = names
    indent = source[source.rfind('\n', 0, block.start())+1:block.start()]
    if indent.strip():
        return []
    first_assignment = first[first.index('='):]
    replacement = f'{capture} {first_assignment.strip()};\n'
    replacement += f'{indent}{second.strip()};\n{indent}{selected} = {mode};\n'
    replacement += f'{indent}{pointer[1]} = {capture};\n{indent}{slot.strip()};'
    declarations = f'\n{indent}void *{capture};\n{indent}s32 {selected};'
    at = part.opening+1
    return [(FAMILY, edit(source, [(at, at, declarations), (block.start(), block.end(), replacement),
                                    (*guard.span('mode'), selected)]))]
