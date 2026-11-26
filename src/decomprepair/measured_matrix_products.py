"""Stage repeated fixed-point products when the measured MIPS registers call for it."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .mips import normalized_integer_lines

FAMILY = 'measured_matrix_products'


def variants(source, name, header, rows):
    part = view(source, name)
    if (not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|s32|u32)\s*;', header)
            or '__repair_product' in source + header):
        return []
    context = source + '\n' + header
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])):
        return []
    lines = [normalized_integer_lines((a, b)) for _, a, b in rows]
    observed = 0
    for i in range(len(lines) - 2):
        (a, b), (c, d), (e, f) = list(lines[i:i+3])
        first = re.fullmatch(r'lh (\$\w+), (.+)', a)
        second = re.fullmatch(r'lw (\$\w+), (.+)', c)
        other_first = re.fullmatch(r'lh (\$\w+), (.+)', b)
        other_second = re.fullmatch(r'lw (\$\w+), (.+)', d)
        if (first and second and other_first and other_second
                and first[2] == other_first[2] and second[2] == other_second[2]
                and first[1] == other_second[1] and second[1] == other_first[1]
                and e == f'mult {first[1]}, {second[1]}'
                and f == f'mult {other_first[1]}, {other_second[1]}'):
            observed += 1
    swapped_loads = 0
    for a, b in lines:
        left = re.fullmatch(r"lh (\$\w+), (.+)", a)
        right = re.fullmatch(r"lh (\$\w+), (.+)", b)
        if left and right and left[2] == right[2] and left[1] != right[1]:
            swapped_loads += 1
    if not observed or swapped_loads < 2:
        return []
    field = rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*s16\s*\*\s*,\s*(?P<off>{NUMBER})\s*\)'
    pattern = re.compile(
        rf'(?P<dest>{field})\s*=\s*\(\s*s16\s*\)\s*\(\s*\(\s*u32\s*\)\s*\(\s*'
        rf'(?P<load>M2C_FIELD\(\s*(?P=base)\s*,\s*s16\s*\*\s*,\s*(?P=off)\s*\))\s*\*\s*'
        rf'(?P<factor>M2C_FIELD\(\s*(?P<factorbase>{IDENT})\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\))'
        rf'\s*\)\s*>>\s*(?P<shift>{NUMBER})\s*\)\s*;')
    hits = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if not 2 <= len(hits) <= 8:
        return []
    changes = [(part.opening + 1, part.opening + 1, '\n    s32 __repair_product;')]
    for hit in hits:
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        names = (hit['base'], hit['factorbase'])
        if ((prefix and prefix[-1] not in ';{}') or re.search(r'/[*/]|#', source[hit.start():hit.end()])
                or any(len(re.findall(rf'\b(?:void|s16|s32)\s*\*\s*{re.escape(n)}\b', part.clean)) != 1
                       for n in names)
                or any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(n)}\b', context) for n in names)):
            return []
        dest, load, factor, shift = (source[slice(*hit.span(k))] for k in ('dest', 'load', 'factor', 'shift'))
        replacement = (f'__repair_product = {load}; __repair_product = __repair_product * {factor}; '
                       f'{dest} = (s16) ((u32) __repair_product >> {shift});')
        changes.append((hit.start(), hit.end(), replacement))
    return [(FAMILY, edit(source, changes))]
