"""Bounded operand rewrites suggested by KMC GCC's MIPS instruction order."""

import re

from .csource import find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view

FLOAT = r'(?:float|double|f32|f64)'
TYPE = rf'(?:struct\s+{IDENT}|{INTEGER}|{FLOAT}|{IDENT})'
DECLARATION = re.compile(rf'\b(?P<type>{TYPE})(?P<pointer>\s*\*\s*|\s+)(?P<name>{IDENT})\s*(?=[,);=])')
ADDU = re.compile(r'addu\s+(\$\w+)\s*,\s*(\$\w+)\s*,\s*(\$\w+)')
LOAD = re.compile(r'l(?:w|d)c1\s+\$\w+\s*,\s*(\S.*)')
COMPARISON = re.compile(r'c\.(?:lt|le)\.[sd]\b')
RELATION = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}


def evidence(rows):
    """Find reversed address inputs and swapped FP loads before an unchanged comparison."""
    address = False
    for marker, left, right in rows:
        a, b = ADDU.fullmatch(left.strip()), ADDU.fullmatch(right.strip())
        if marker != ' ' and a and b and a[2] != a[3] and a.groups() == (b[1], b[3], b[2]):
            address = True
            break
    for i, (marker, left, _) in enumerate(rows):
        if marker != ' ' or not COMPARISON.match(left.strip()):
            continue
        window = rows[max(0, i - 5):i]
        a, b = ([match[1] for row in window if (match := LOAD.fullmatch(row[col].strip()))]
                for col in (1, 2))
        if len(a) == len(b) == 2 and a[0] != a[1] and a == b[::-1]:
            return address, True
    return address, False


def variants(source, name, header, rows):
    address, comparison = evidence(rows)
    if not (address or comparison) or not (part := view(source, name)):
        return []
    if re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')\b', header+'\n'+source, re.M))
    declared = {}
    # Restrict declaration recognition to parameter and statement boundaries.
    start, _ = find(source, name)
    for match in DECLARATION.finditer(part.clean, start, part.end):
        prefix = part.clean[:match.start()].rstrip()
        if not prefix or prefix[-1] not in '(,;{}':
            continue
        key = match['name']
        kind = (match['type'], '*' in match['pointer'])
        declared[key] = kind if key not in declared else None

    candidates = []
    if address:
        index = rf'(?:{IDENT}|{NUMBER})'
        indexed = rf'&\s*(?P<base>{IDENT})\s*\[\s*(?P<index>{index})\s*\]'
        pointer = rf'(?P<base>{IDENT})\s*\+\s*(?P<index>{index})'
        # Plain value assignments and returns avoid partially rewriting larger arithmetic expressions.
        pattern = r'(?:\breturn\s+|(?<![=<>!+\-*/&|^%])=(?!=)\s*)'
        for expression in (indexed, pointer):
            for match in re.finditer(pattern + rf'(?P<expr>{expression})(?=\s*;)', part.body):
                base, offset = match['base'], match['index']
                declaration = declared.get(base)
                offset_type = declared.get(offset)
                if (not declaration or not declaration[1] or declaration[0] == 'void'
                        or {base, offset, *declaration[0].split()} & macros
                        or not (re.fullmatch(NUMBER, offset) or
                                offset_type and not offset_type[1] and re.fullmatch(INTEGER, offset_type[0]))):
                    continue
                scaled = f'((unsigned int){offset} * (unsigned int)sizeof(*{base}))'
                replacement = f'({declaration[0]} *)({scaled} + (unsigned int){base})'
                start, end = match.span('expr')
                candidates.append(('kmc_address_operand_order',
                                   edit(source, [(part.opening+1+start, part.opening+1+end, replacement)])))
                if len(candidates) >= 4:
                    break
            if len(candidates) >= 4:
                break
    if comparison:
        for match in re.finditer(rf'\b(?:if|while)\s*\(\s*(?P<expr>({IDENT})\s*(<=|>=|<|>)\s*({IDENT}))\s*\)', part.body):
            _, a, op, b = match.groups()
            if a == b or {a,b} & macros or any(not (kind := declared.get(v)) or kind[1]
                                              or not re.fullmatch(FLOAT, kind[0]) for v in (a,b)):
                continue
            start, end = match.span('expr')
            candidates.append(('kmc_float_comparison_order', edit(source, [
                (part.opening+1+start, part.opening+1+end, f'{b} {RELATION[op]} {a}')])))
            if sum(family == 'kmc_float_comparison_order' for family, _ in candidates) >= 4:
                break
    return candidates
