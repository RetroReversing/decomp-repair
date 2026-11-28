"""Hold a nonvolatile record field shared by consecutive if/else-if checks.

On a KMC MIPS O1 state machine, keeping the error field in one local removed
four redundant instructions and improved the linked judge from 415 to 10.
The second check only runs when the first arm is not taken, so no code can
change the field between those two reads. Volatile or macro-sensitive types,
fields, indexes and declarations are rejected.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'hold_field_ladder'
LIMIT = 8


def variants(source, name, header=''):
    part = view(source, name)
    context = _blank(source) + '\n' + _blank(header)
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', context):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', context))
    pattern = rf'\bif\s*\(\s*(?P<array>{IDENT})\s*\[\s*(?P<index>{IDENT})\s*\]\s*\.\s*(?P<field>{IDENT})\s*==\s*{NUMBER}\s*\)'
    result = []
    for hit in re.finditer(pattern, part.clean[part.opening:part.end]):
        array, index, field = hit['array'], hit['index'], hit['field']
        if {array, index, field} & macros:
            continue
        declaration = re.search(rf'\bextern\s+({IDENT})\s+{re.escape(array)}\s*\[\s*\]\s*;', context)
        if not declaration or declaration[1] in macros:
            continue
        struct_type = declaration[1]
        struct = re.search(rf'\btypedef\s+struct\s*{{([^{{}}]*)}}\s*{re.escape(struct_type)}\s*;', context)
        if not struct or re.search(r'\bvolatile\b', struct[1]):
            continue
        member = re.search(rf'\b({INTEGER})\s+{re.escape(field)}\s*;', struct[1])
        if not member or member[1] in macros or re.search(rf'\btypedef\b[^;]*\bvolatile\b[^;]*\b{re.escape(member[1])}\s*;', context):
            continue
        start = part.opening + hit.start()
        before = part.clean[part.opening + 1:start].rstrip()
        if before and before[-1] not in ';{}:':
            continue  # do not move the load outside an unbraced conditional
        end_if = part.opening + hit.end()
        brace = re.match(r'\s*{', part.clean[end_if:part.end])
        first_end = close(part.clean, end_if + brace.end() - 1, '{', '}') if brace else None
        second = re.match(rf'\s*else\s+if\s*\(\s*{re.escape(array)}\s*\[\s*{re.escape(index)}\s*\]\s*\.\s*{re.escape(field)}\s*!=\s*0\s*\)', part.clean[first_end:part.end]) if first_end else None
        if not second:
            continue
        # Neither the array name nor the index may be shadowed by a local declaration.
        body = part.body
        if re.search(rf'\b(?:{INTEGER}|{IDENT})\s+\*?\s*(?:{re.escape(array)}|{re.escape(index)})\s*(?:[;=,\[])', body):
            # The index is normally a function local; only the array itself must not be shadowed.
            if re.search(rf'\b(?:{INTEGER}|{IDENT})\s+\*?\s*{re.escape(array)}\s*(?:[;=,\[])', body):
                continue
        temp = '__repair_held_' + field
        if re.search(r'\b' + re.escape(temp) + r'\b', context):
            continue
        first_expr = re.search(rf'{re.escape(array)}\s*\[\s*{re.escape(index)}\s*\]\s*\.\s*{re.escape(field)}', part.clean[start:end_if])
        second_expr = re.search(rf'{re.escape(array)}\s*\[\s*{re.escape(index)}\s*\]\s*\.\s*{re.escape(field)}', part.clean[first_end:first_end + second.end()])
        a, b = start + first_expr.start(), first_end + second_expr.start()
        expr = source[a:start + first_expr.end()]
        edits = [(part.opening + 1, part.opening + 1, f'\n    {member[1]} {temp};'),
                 (start, start, f'{temp} = {expr};\n'),
                 (a, start + first_expr.end(), temp), (b, first_end + second_expr.end(), temp)]
        result.append((FAMILY, edit(source, edits)))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
