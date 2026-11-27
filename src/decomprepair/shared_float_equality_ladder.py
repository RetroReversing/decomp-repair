"""Join duplicate float-equality arms behind two direct branches.

A large N64 function called the same rotation helper for either of two float equality tests, and used a different
call otherwise. Its target branched directly to the shared call arm. Writing the two tests as direct branches to
one copy scored 49,305 -> 48,525 under KMC GCC 2.7.2 -G0 -mips3 -mgp32 -mfp32 -O2, and 5,615 -> 3,860 in an
-O1 diagnostic. This is one observation, not a match. The compared value must be a plain nonvolatile float local,
the two bodies textually identical, and the target must show two float equality branches to one label.
"""
import re

from .csource import find
from .float_comparisons_shared_arm import FLOAT, evidence
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'shared_float_equality_ladder'
FAMILIES = (FAMILY,)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_EQ = re.compile(rf'\s*(?P<var>{IDENT})\s*==\s*(?P<value>{FLOAT})\s*')
_MACRO = re.compile(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
                    r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)[ \t]*$')


def _arm(clean, at, limit):
    head = _IF.match(clean, at)
    if not head:
        return None
    end = close(clean, head.end() - 1)
    condition = _EQ.fullmatch(clean[head.end():end - 1]) if end else None
    opening = re.match(r'\s*\{', clean[end:limit]) if end else None
    if not condition or not opening:
        return None
    brace = end + opening.end() - 1
    tail = close(clean, brace, '{', '}')
    return (condition, brace, tail) if tail else None


def variants(source, name, asm, header=''):
    if not evidence(asm):
        return []
    part, span = view(source, name), find(source, name)
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    macros = source + '\n' + (header or '')
    if (re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bf32\s*;', macros)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+f32\b', macros)):
        return []
    clean, out = part.clean, []
    for first in _IF.finditer(clean, part.opening + 1, part.end):
        arm = _arm(clean, first.start(), part.end)
        if not arm:
            continue
        cond, brace, end = arm
        next_if = re.match(r'\s*else\s+(?=if\b)', clean[end:part.end])
        second = _arm(clean, end + next_if.end(), part.end) if next_if else None
        if not second or second[0]['var'] != cond['var'] or second[0]['value'] == cond['value']:
            continue
        other = re.match(r'\s*else\s*\{', clean[second[2]:part.end])
        if not other:
            continue
        other_open = second[2] + other.end() - 1
        other_end = close(clean, other_open, '{', '}')
        if not other_end:
            continue
        var = cond['var']
        if (len(re.findall(rf'\bf32\s+{re.escape(var)}\s*;', clean[part.opening:part.end])) != 1
                or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(var)}\b', macros)):
            continue
        shared, duplicate, normal = source[brace:end], source[second[1]:second[2]], source[other_open:other_end]
        if shared.strip() != duplicate.strip() or re.search(r'/[*/]|#', source[first.start():other_end]):
            continue
        arms = clean[brace:other_end]
        if re.search(r'\b(?:case|default|goto|break|continue|return|static)\b|\b' + IDENT + r'\s*:(?!:)', arms):
            continue
        if re.search(r'\b__(?:LINE|FILE|COUNTER)__\b', shared + normal):
            continue
        tokens = re.findall(r'\b[A-Za-z_]\w*\b', shared + normal)
        if any(token != 'M2C_FIELD' and re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(token)}\b', macros)
               for token in tokens):
            continue
        if 'M2C_FIELD' in tokens and (len(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b', macros)) != 1
                                      or not _MACRO.search(macros)):
            continue
        index = 0
        while re.search(rf'\bshared_(?:arm|done)_{index}\b', macros):
            index += 1
        shared_label, done_label = f'shared_arm_{index}', f'shared_done_{index}'
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, first.start()) + 1:first.start()])[0]
        replacement = (f'if ({var} == {cond["value"]}) goto {shared_label};\n'
                       f'{indent}if ({var} == {second[0]["value"]}) goto {shared_label};\n'
                       f'{indent}{normal}\n{indent}goto {done_label};\n{shared_label}:\n'
                       f'{indent}{shared}\n{done_label}:;')
        out.append((FAMILY, edit(source, [(first.start(), other_end, replacement)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
