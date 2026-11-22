"""Store a selected halfword in each arm when target branch layout warrants it."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'bnez \$(?P<test>\w+), [^\n]+\nsw \$\w+, \d+\(\$(?P<base>\w+)\)\n'
    r'j [^\n]+\naddiu \$(?P<value>\w+), \$zero, (?P<first>\d+)\n'
    r'addiu \$(?P=value), \$zero, (?P<second>\d+)\n'
    r'sh \$(?P=value), \(\$(?P=base)\)'
)
_PATTERN = re.compile(
    rf'if\s*\(\s*(?P<test>{IDENT})\s*==\s*0\s*\)\s*{{\s*'
    rf'(?P<left>(?P<var>{IDENT})\s*=\s*(?P<first>{NUMBER})\s*;)\s*}}\s*else\s*{{\s*'
    rf'(?P<right>(?P=var)\s*=\s*(?P<second>{NUMBER})\s*;)\s*}}'
    rf'(?P<tail>\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*s16\s*\*\s*,\s*0\s*\)\s*=\s*(?P=var)\s*;)'
)
_MACRO = re.compile(
    r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
    r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*'
)


def variants(source, name, header, rows):
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.search(target)
    if not witness or not 20 <= len(rows) <= 80:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    # Require the opposite constant order in the candidate, with the same final store.
    shape = (rf'addiu \$\w+, \$zero, {witness["second"]}\n'
             rf'addiu \$\w+, \$zero, {witness["first"]}\n')
    if not re.search(shape, candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__)\b', part.clean):
        return []
    part.end = end
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', source + '\n' + header)
    if len(definitions) != 1 or not _MACRO.fullmatch(definitions[0]):
        return []
    hits = list(_PATTERN.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    if (integer(hit['first']) != int(witness['first']) or integer(hit['second']) != int(witness['second'])
            or hit['base'] == hit['var'] or hit['test'] == hit['var']
            or len(re.findall(rf'\b{re.escape(hit["var"])}\b', part.body)) != 4
            or not any(d['name'] == hit['var'] and d['type'] == 's16' for d in locals_for(part))):
        return []
    offset = part.opening + 1
    original = source[offset + hit.start():offset + hit.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    dst = f'M2C_FIELD({hit["base"]}, s16 *, 0)'
    fixed = edit(source, [(offset + hit.start('left'), offset + hit.end('left'), f'{dst} = {hit["first"]};'),
                          (offset + hit.start('right'), offset + hit.end('right'), f'{dst} = {hit["second"]};'),
                          (offset + hit.start('tail'), offset + hit.end('tail'), '')])
    return [('measured_branch_halfword_store', fixed)]
