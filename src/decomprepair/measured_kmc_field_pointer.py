"""Keep a field pointer live across the observed KMC branch and call."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close


def variants(source, name, header, rows):
    if len(rows) != 30:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (not re.search(r'\baddiu \$s1, \$v1, 4\b', target)
            or not re.search(r'(?m)^jal ', target)
            or target.count('sb $zero, 7($s1)') != 2
            or ('sb $zero, 7($s1)', 'sb $zero, 11($s1)') not in changes
            or ('addiu $s1, $v1, 4', 'slti $v0, $a0, 4') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = part.body
    field = re.search(rf'M2C_FIELD\((?P<address>\(\s*(?P<base>{IDENT})\s*\+\s*4\s*\)),\s*s8\s*\*,\s*7\s*\)', body)
    if not field or re.search(r'\bvolatile\b|\b__repair_field_ptr\b', part.clean):
        return []
    base = field['base']
    if not re.search(rf'\bvoid\s*\*\s*{re.escape(base)}\s*;', body):
        return []
    assignments = list(re.finditer(rf'\b{re.escape(base)}\s*=\s*M2C_FIELD\([^;]+\);', body))
    if (len(assignments) != 1 or assignments[0].end() >= field.start()
            or re.search(rf'\b{re.escape(base)}\s*(?:[+*/&|^-]?=|\+\+|--)', body[assignments[0].end():])
            or re.search(rf'(?:&|\+\+|--)\s*{re.escape(base)}\b', body)
            or not re.search(r'\b[A-Za-z_]\w*\s*\(', body[assignments[0].end():field.start()])):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start, start, '\n    void *__repair_field_ptr;'),
                          (start + assignments[0].end(), start + assignments[0].end(),
                           f'\n    __repair_field_ptr = {base} + 4;'),
                          (start + field.start('address'), start + field.end('address'),
                           '__repair_field_ptr')])
    return [('measured_live_field_pointer', fixed)]
