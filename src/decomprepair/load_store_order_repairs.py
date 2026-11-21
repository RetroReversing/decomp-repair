"""A load through a pointer written before the global store m2c put ahead of it.

gcc may not move a load through a pointer above a store to a global that the pointer could alias, so the order of
the two statements in the C is the order of the instructions. m2c follows the order the stores appear, and a load
the game did first lands after the store:

    D_800E1A68 = 0;
    D_800C7E6C = M2C_FIELD(arg0, u8 *, 0x44);

An N64 function was 96.2% this way and exact with the two statements swapped. The swap changes meaning only when the
pointer reaches the global, which is what the judge's byte comparison settles.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'load_before_store'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>' + IDENT + r')\s*=(?!=)\s*(?P<rhs>[^;{}]*);[ \t]*\n')
LOAD = re.compile(r'\bM2C_FIELD\s*\(|->|\*\s*\(|\[')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    locals_ = set(re.findall(r'(?m)^[ \t]*(?:[\w ]+?)[\s*]+(' + IDENT + r')\s*(?:\[[^]]*\])?\s*;', body))
    result = []
    for first in STATEMENT.finditer(clean, opening + 1, end):
        second = STATEMENT.match(clean, first.end())
        if not second or second['indent'] != first['indent']:
            continue
        stored, value = first['lhs'], first['rhs']
        # a global stored with a plain value (no load, no call), then a statement that loads through a pointer
        if stored in locals_ or LOAD.search(value) or re.search(IDENT + r'\s*\(', value):
            continue
        if not LOAD.search(second['rhs']) or re.search(IDENT + r'\s*\(', second['rhs'].replace('M2C_FIELD(', '')):
            continue
        if re.search(r'\b' + re.escape(stored) + r'\b', second.group(0)) \
                or re.search(r'\b' + re.escape(second['lhs']) + r'\b', first.group(0)):
            continue
        text = (source[:first.start()] + source[second.start():second.end()] + source[first.start():first.end()]
                + source[second.end():])
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result


COMPONENT_BEFORE_RESETS = 'component_before_global_resets'
REG = r'\$\w+'
NUMBER = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
COMPONENT_TARGET = re.compile(
    rf'(?m)^lwc1 (?P<value>{REG}), (?:0x)?8\({REG}\)\n'
    rf'lui (?P<first_reg>{REG}), %hi\((?P<first>{IDENT})\)\n'
    r'sw \$zero, %lo\((?P=first)\)\((?P=first_reg)\)\n'
    rf'lui (?P<second_reg>{REG}), %hi\((?P<second>{IDENT})\)\n'
    r'sw \$zero, %lo\((?P=second)\)\((?P=second_reg)\)\n'
    rf'beqz {REG}, \.L\w+\n'
    rf'swc1 (?P=value), {NUMBER}\(\$sp\)$'
)


def component_before_resets(source, name, asm, header=''):
    """Schedule the third input component before two independent pointer resets."""
    from .integer_repair_support import view

    if 'swc1' not in asm or not (part := view(source, name)):
        return []
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    lines = '\n'.join(' '.join(line.split()) for line in assembly.splitlines())
    declarations = _blank(header) + '\n' + part.clean[:part.opening]
    for target in COMPONENT_TARGET.finditer(lines):
        first, second = target['first'], target['second']
        if first == second or any(not re.search(rf'\bextern\s+void\s*\*+\s*{name}\s*;', declarations)
                                  for name in (first, second)):
            continue
        sequence = re.compile(
            rf'(?m)^(?P<global>[ \t]*{first}\s*=\s*(?:NULL|0)\s*;[ \t]*\n'
            rf'[ \t]*{second}\s*=\s*(?:NULL|0)\s*;[ \t]*\n)'
            rf'(?P<read>[ \t]*(?P<vector>{IDENT})\.(?P<field>{IDENT})\[2\]\s*=\s*'
            rf'M2C_FIELD\(\s*(?P<input>{IDENT})\s*,\s*f32\s*\*\s*,\s*(?:8|0x8)\s*\)\s*;[ \t]*\n)'
        )
        for hit in sequence.finditer(part.clean, part.opening + 1, part.end):
            vector, field, origin = hit['vector'], hit['field'], hit['input']
            prefix = part.clean[part.opening + 1:hit.start()]
            storage = re.search(rf'(?m)^\s*(?P<type>{IDENT})\s+{vector}\s*;', prefix)
            if not storage or not re.search(
                    rf'typedef\s+struct\s*{{\s*f32\s+{field}\s*\[\s*3\s*\]\s*;\s*}}\s*{storage["type"]}\s*;',
                    declarations):
                continue
            if origin in (first, second, vector) or any(
                    re.search(rf'\b(?:void|s32|u32|int)\s*\*+\s*{symbol}\b', prefix)
                    for symbol in (first, second)):
                continue
            prefix = prefix.rstrip()
            if not prefix.endswith((';', '{', '}')):
                continue
            read = source[hit.start('read'):hit.end('read')]
            resets = source[hit.start('global'):hit.end('global')]
            return [(COMPONENT_BEFORE_RESETS, source[:hit.start()] + read + resets + source[hit.end():])]
    return []
