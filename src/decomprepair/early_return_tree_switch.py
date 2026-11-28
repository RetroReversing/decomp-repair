"""Recover a three-value switch from an early-return compare tree.

A KMC GCC 2.7.2 -O1 state handler's opening tree was read as nested
inequalities. Restoring its three cases improved the local linked score from
12172 to 10402. The middle value falls through to the following statements;
the adjacent values have their own bodies and return, as does the default.
"""
import re

from .compare_tree_default_switch import _statement_if
from .csource import _blank, find
from .integer_repair_support import IDENT

FAMILY = 'early_return_tree_switch'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)'
CAST = r'(?:\(\s*(?:s32|int|signed\s+int)\s*\)\s*)?'


def _condition(text, op):
    match = re.fullmatch(rf'\s*{CAST}(?P<name>{IDENT})\s*{op}\s*(?P<n>{NUMBER})\s*', text)
    return (match['name'], int(match['n'], 0)) if match else None


def _guard(clean, at, end, name, value):
    parsed = _statement_if(clean, at)
    if not parsed or parsed[2] or parsed[3] > end:
        return None
    if _condition(clean[parsed[0][0]:parsed[0][1]], '!=') != (name, value):
        return None
    if not re.fullmatch(r'\s*return\s*;\s*', clean[parsed[1][0]:parsed[1][1]]):
        return None
    return parsed[3]


def _body(source, clean, start, end):
    text = clean[start:end]
    if not re.search(r'\breturn\s*;\s*$', text):
        return None
    # A switch would capture an outer break, and labels or jumps could enter or
    # leave its arms. C declarations are avoided because a case is not a scope.
    if re.search(r'\b(?:break|continue|goto|case|default|asm|__asm__)\b|(?<![\w?:])'+IDENT+r'\s*:(?!:)', text):
        return None
    if re.search(r'(?:^|[;{}])\s*(?:(?:const|volatile|static|struct)\s+)*'+IDENT
                 + r'\s*(?:\*\s*|\s+)'+IDENT+r'\s*(?:[;=,\[])', text):
        return None
    return source[start:end].strip()


def variants(source, name, header='', flags=None):
    if any(flag.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor')) for flag in flags or ()):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    if (re.search(r'(?m)^\s*#\s*include\b', source + '\n' + header)
            or re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', clean[opening:span[1]])):
        return []
    macros = '\n'.join(re.findall(r'(?m)^\s*#\s*define\b[^\n]*(?:\\\n[^\n]*)*', source + '\n' + header))
    macro_names = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', macros))
    if macro_names & {'if', 'else', 'switch', 'case', 'default', 'break', 'return', 's32', 'int', 'signed'}:
        return []
    out = []
    for hit in re.finditer(r'\bif\s*\(', clean[opening + 1:span[1]]):
        at = opening + 1 + hit.start()
        outer = _statement_if(clean, at)
        if not outer or outer[2]:
            continue
        condition = _condition(clean[outer[0][0]:outer[0][1]], '!=')
        if not condition:
            continue
        variable, middle = condition
        if middle < 1 or middle >= 0x7fffffff or re.search(rf'\b{re.escape(variable)}\b', macros):
            continue
        # A local non-volatile signed int gives all three tests the same value.
        function_text = clean[span[0]:span[1]]
        declarations = list(re.finditer(rf'\b(?P<type>(?:(?:volatile|static|register|const)\s+)*(?:s32|int|signed\s+int))\s+(?P<name>{re.escape(variable)})\b', function_text))
        if len(declarations) != 1 or re.search(r'\b(?:volatile|static)\b', declarations[0]['type']):
            continue
        # A different-typed nested declaration can shadow the chosen local.
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(variable)})\s*(?:[;=,\[)]|$)')
        if any(match.start('name') != declarations[0].start('name') for match in re.finditer(shadow, function_text)):
            continue
        # The alias is not assumed to have its conventional width or signedness.
        if re.search(r'\bs32\b', declarations[0]['type'] + clean[at:outer[3]]):
            aliases = re.findall(r'\btypedef\s+([^;{}]+)\s+s32\s*;', _blank(source + '\n' + header))
            if not aliases or any(' '.join(alias.split()) not in ('int', 'signed', 'signed int') for alias in aliases):
                continue
        if re.search(rf'&\s*{re.escape(variable)}\b', clean[span[0]:span[1]]):
            continue
        high_at = outer[1][0] + len(clean[outer[1][0]:outer[1][1]]) - len(clean[outer[1][0]:outer[1][1]].lstrip())
        high = _statement_if(clean, high_at)
        if not high or high[2] or high[3] >= outer[1][1]:
            continue
        if _condition(clean[high[0][0]:high[0][1]], '>=') != (variable, middle + 1):
            continue
        guard_at = high[1][0] + len(clean[high[1][0]:high[1][1]]) - len(clean[high[1][0]:high[1][1]].lstrip())
        high_start = _guard(clean, guard_at, high[1][1], variable, middle + 1)
        low_at = high[3] + len(clean[high[3]:outer[1][1]]) - len(clean[high[3]:outer[1][1]].lstrip())
        low_start = _guard(clean, low_at, outer[1][1], variable, middle - 1)
        if high_start is None or low_start is None:
            continue
        high_body = _body(source, clean, high_start, high[1][1])
        low_body = _body(source, clean, low_start, outer[1][1])
        if high_body is None or low_body is None:
            continue
        # A macro expansion could hide an outer break, goto or declaration.
        if macro_names.intersection(re.findall(IDENT, clean[high_start:high[1][1]] + clean[low_start:outer[1][1]])):
            continue
        indent = re.search(r'[ \t]*$', source[:at])[0]
        replacement = (f'switch ({variable}) {{\n{indent}case {middle - 1}:\n{indent}    {low_body}\n'
                       f'{indent}case {middle}:\n{indent}    break;\n{indent}case {middle + 1}:\n'
                       f'{indent}    {high_body}\n{indent}default:\n{indent}    return;\n{indent}}}')
        out.append((FAMILY, source[:at] + replacement + source[outer[3]:]))
        if len(out) == 4:
            break
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'), 'archs': ('mips',)}
