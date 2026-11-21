"""`0.0f` stores written through a float zero, where the target stores the FPU's zero.

gcc 2.7.2 stores a literal `0.0f` into a float field as an integer zero (`sw $zero`); the game stored `$f0` after
`mtc1 $zero, $f0`. An N64 function clearing a vector's three components (0% so) was exact with them set from one
`f32` local (or a chained assignment). Offered only when the target has `mtc1 $zero`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_zero_local'
FAMILIES = (FAMILY,)


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm or not re.search(r'\bmtc1\s+\$zero\b', asm):
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    stores = list(re.finditer(r'=\s*0\.0f?\s*;', clean[opening:end]))
    if not stores or '__repair_fzero' in clean:
        return []
    text = source
    for m in reversed(stores):
        a = opening + m.start()
        text = text[:a] + '= __repair_fzero;' + text[opening + m.end():]
    text = text[:opening + 1] + '\n    f32 __repair_fzero = 0.0f;\n' + text[opening + 1:]
    return [(FAMILY, text)]


def loop_variants(source, name, asm, header=''):
    """Share a float-zero carrier across repeated stack-vector clears in a loop."""
    from .integer_repair_support import IDENT, edit, view

    if 'swc1' not in asm or not (part := view(source, name)):
        return []
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    stack_store = re.compile(r'\bswc1\s+(\$\w+),\s*(0x[0-9a-fA-F]+|[0-9]+)\(\$sp\)')
    zero_registers = set(re.findall(r'\bmtc1\s+\$zero,\s*(\$\w+)', assembly))
    if not zero_registers:
        return []
    slots = {}
    for register, offset in stack_store.findall(assembly):
        if register in zero_registers:
            slot = (register, int(offset, 0))
            slots[slot] = 1 + slots.get(slot, 0)
    if not any(count >= 3 and all(slots.get((register, offset + step), 0) >= 3 for step in (4, 8))
               for (register, offset), count in slots.items()):
        return []

    initial = re.compile(
        rf'\bdo\s*{{(?P<gap>\s*)\{{\s*(?:register\s+)?(?P<type>f32|float)\s+(?P<zero>{IDENT})\s*=\s*0\.0f\s*;'
        rf'\s*(?P<array>{IDENT})\[2\]\s*=\s*(?P=zero)\s*;\s*(?P=array)\[1\]\s*=\s*(?P=zero)\s*;'
        r'\s*(?P=array)\[0\]\s*=\s*(?P=zero)\s*;\s*}'
    )
    for match in initial.finditer(part.clean, part.opening, part.end):
        array = match['array']
        definition = (rf'(?:^|[;{{])\s*(?:f32|float)\s+{array}\s*'
                      r'\[\s*(?:[3-9]|[1-9][0-9]+)\s*\]\s*;')
        declarations = re.findall(rf'\b(?:f32|float)\s+{array}\s*\[', part.body)
        if len(declarations) != 1 or not re.search(definition, part.clean[part.opening:match.start()]):
            continue
        loop_open = part.clean.find('{', match.start(), match.start('gap'))
        end = close(part.clean, loop_open, '{', '}')
        if not end or re.search(r'(?m)^\s*[A-Za-z_]\w*\s*:', part.clean[match.end():end]):
            continue
        zero_store = rf'\b{array}\s*\[\s*{{index}}\s*\]\s*=\s*(?P<zero{{index}}>0\.0f)\s*;'
        triples = re.compile(r'\s*'.join(zero_store.format(index=index) for index in (2, 1, 0)))
        groups = list(triples.finditer(part.clean, match.end(), end))
        if len(groups) < 2:
            continue
        used = set(re.findall(IDENT, part.clean + '\n' + header))
        carrier = '__repair_loop_fzero'
        while carrier in used:
            carrier += '_'
        gap = match['gap']
        inline = f'{match["type"]} {carrier} = 0.0f;{gap}' + gap.join(
            f'{array}[{index}] = {carrier};' for index in (2, 1, 0))
        changes = [(match.end('gap'), match.end(), inline)]
        changes += [(*hit.span(f'zero{index}'), carrier) for hit in groups for index in (2, 1, 0)]
        return [('loop_float_zero', edit(source, changes))]
    return []
