"""Offer two direct float branches to an existing else arm.

A large N64 function tested `x != 1.0f && x != -1.0f`, while its target branches twice on equality to the same
else arm. Making those two branches explicit reduced the exact judge from 50,125 to 49,265 at KMC GCC 2.7.2
-G0 -mips3 -mgp32 -mfp32 -O2 and from 6,970 to 5,970 in an -O1 diagnostic. This is one observation, not a match.
The rewrite keeps each original arm in its own scope and reads only a plain nonvolatile float local. It requires
assembly evidence of two floating equality branches sharing a target; the judge decides which source shape wins.
"""
import re
from collections import Counter

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'float_comparisons_shared_arm'
FAMILIES = (FAMILY,)
LIMIT = 8
FLOAT = r'-?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)[fF]'
_IF = re.compile(r'\bif\s*\(')
_COND = re.compile(rf'\s*\(\s*(?P<var>{IDENT})\s*!=\s*(?P<a>{FLOAT})\s*\)\s*&&\s*'
                   rf'\(\s*(?P=var)\s*!=\s*(?P<b>{FLOAT})\s*\)\s*')


def evidence(asm):
    """Two MIPS floating comparisons of one register branch to the same target."""
    text = re.sub(r'/\*[^\n]*?\*/', '', asm or '')
    pattern = re.compile(r'(?m)^[ \t]*c\.eq\.s[ \t]+\$(\w+)\s*,\s*\$\w+\s*\n'
                         r'(?:[ \t]*nop[ \t]*\n){0,4}[ \t]*bc1t[ \t]+(\.L\w+)\b')
    return any(count >= 2 for count in Counter(pattern.findall(text)).values())


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
    for head in _IF.finditer(clean, part.opening + 1, part.end):
        cond_end = close(clean, head.end() - 1)
        if not cond_end or not (condition := _COND.fullmatch(clean[head.end():cond_end - 1])):
            continue
        var, a, b = condition['var'], condition['a'], condition['b']
        decl = re.findall(rf'\bf32\s+{re.escape(var)}\s*;', clean[part.opening:part.end])
        if len(decl) != 1 or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(var)}\b', macros):
            continue
        opening = re.match(r'\s*\{', clean[cond_end:part.end])
        if not opening:
            continue
        first_open = cond_end + opening.end() - 1
        first_end = close(clean, first_open, '{', '}')
        if not first_end:
            continue
        other = re.match(r'\s*else\s*\{', clean[first_end:part.end])
        if not other:
            continue
        second_open = first_end + other.end() - 1
        second_end = close(clean, second_open, '{', '}')
        if not second_end:
            continue
        arms = clean[first_open:second_end]
        if (re.search(r'\b(?:case|default|goto|break|continue|return|static)\b|\b' + IDENT + r'\s*:(?!:)', arms)
                or re.search(r'/[*/]|#', source[head.start():second_end])):
            continue
        index = 0
        while re.search(rf'\bbranch_(?:else|done)_{index}\b', macros):
            index += 1
        other_label, done_label = f'branch_else_{index}', f'branch_done_{index}'
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, head.start()) + 1:head.start()])[0]
        first = source[first_open:first_end]
        second = source[second_open:second_end]
        replacement = (f'if ({var} == {a}) goto {other_label};\n{indent}if ({var} == {b}) goto {other_label};\n'
                       f'{indent}{first}\n{indent}goto {done_label};\n{other_label}:\n{indent}{second}\n{done_label}:;')
        out.append((FAMILY, edit(source, [(head.start(), second_end, replacement)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
