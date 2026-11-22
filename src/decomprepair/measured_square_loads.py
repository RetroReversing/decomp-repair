"""Inline adjacent nonvolatile word loads used twice in component-wise products."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_square_loads'


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    # These are the standard m2c macros, not arbitrary macros that may have side effects.
    macros = source + '\n' + header
    if (re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bs32\s*;', macros)
            or len(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b', macros)) != 1):
        return []
    if not re.search(r'#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
                     r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)', macros):
        return []
    lines = [normalized_integer_lines((left, right)) for _, left, right in rows]
    # The candidate stalls after a word load; the target feeds the same multiply directly.
    stalls = 0
    for i in range(1, len(lines) - 1):
        left, right = lines[i]
        if not left and right == 'nop' and lines[i-1][0] == lines[i-1][1] and lines[i+1][0] == lines[i+1][1]:
            load = re.fullmatch(r'lw (\$\w+), .*', lines[i-1][0])
            if load and lines[i+1][0] == f'mult {load[1]}, {load[1]}':
                stalls += 1
    if stalls < 2:
        return []
    pattern = re.compile(
        rf'(?P<local>{IDENT})\s*=\s*(?P<load>M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\))\s*;\s*'
        rf'(?P<store>M2C_FIELD\(\s*{IDENT}\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\)\s*=\s*\(\s*s32\s*\)\s*\()'
        rf'(?P=local)\s*\*\s*(?P=local)\s*\)\s*;')
    decls = {d['name']: d for d in locals_for(part)}
    hits = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if not 2 <= len(hits) <= 8:
        return []
    # Restrict to a straight-line function with just declarations and these pairs.
    end = close(part.clean, part.opening, "{", "}")
    if not end:
        return []
    remainder = part.clean[part.opening + 1:end - 1]
    for hit in reversed(hits):
        a, b = hit.start() - part.opening - 1, hit.end() - part.opening - 1
        remainder = remainder[:a] + remainder[b:]
    if re.sub(rf'\bs32\s+{IDENT}\s*;', '', remainder).strip():
        return []
    edits = []
    for hit in hits:
        local = hit['local']
        if re.search(rf'(?m)^\s*#\s*define\s+(?:s32|{re.escape(hit["base"])})\b', macros):
            return []
        if (local not in decls or decls[local]['type'] != 's32'
                or len(re.findall(rf'\b{re.escape(local)}\b', part.body)) != 4
                or re.search(r'/[*/]|#', source[hit.start():hit.end()])
                or re.search(rf'(?m)^\s*#\s*define[^\n]*\b{re.escape(local)}\b', macros)):
            return []
        expression = source[slice(*hit.span('load'))]
        store = source[slice(*hit.span('store'))]
        edits.append((hit.start(), hit.end(), f'{store}{expression} * {expression});\n    '))
    return [(FAMILY, edit(source, edits))]
