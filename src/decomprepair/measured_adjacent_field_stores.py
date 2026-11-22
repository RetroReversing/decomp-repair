"""Swap independent adjacent field stores whose target order is reversed."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_adjacent_field_stores'
FAMILIES = (FAMILY,)

OPS = {'sb': 1, 'sh': 2, 'sw': 4}
TYPES = {'s8': ('sb', r'(?:signed\s+)?char'), 'u8': ('sb', r'unsigned\s+char'),
         's16': ('sh', r'(?:signed\s+)?short(?:\s+int)?'), 'u16': ('sh', r'unsigned\s+short(?:\s+int)?'),
         's32': ('sw', r'(?:signed\s+)?int'), 'u32': ('sw', r'unsigned\s+int')}
ASM_STORE = re.compile(r'(?P<op>sb|sh|sw) (?P<value>\$\w+), (?P<offset>-?\d+)?\((?P<base>\$\w+)\)')
FIELD = re.compile(rf'(?m)^(?P<indent>[ \t]*)M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*'
                   rf'(?P<type>s8|u8|s16|u16|s32|u32)\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)\s*=\s*'
                   rf'(?P<value>{IDENT}|{NUMBER})\s*;[ \t]*(?:\n|$)')


def _stores(lines):
    return [(index, match) for index, line in enumerate(lines) if (match := ASM_STORE.fullmatch(line))]


def variants(source, name, header, rows):
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    span = find(source, name)
    if (not end or not span or re.search(r'\b(?:volatile|asm|__asm__)\b|(?m:^\s*#)',
                                         part.clean[span[0]:end - 1])):
        return []
    target, candidate = ([*normalized_integer_lines(row[side] for row in rows if row[side])] for side in (1, 2))
    target_stores, candidate_stores = _stores(target), _stores(candidate)
    pairs = []
    for (i, first), (j, second) in zip(target_stores, target_stores[1:]):
        if j != i + 1 or first['base'] != second['base']:
            continue
        a, b = int(first['offset'] or '0'), int(second['offset'] or '0')
        if a < b + OPS[second['op']] and b < a + OPS[first['op']]:
            continue
        if not any(y == x + 1 and c[0] == second[0] and d[0] == first[0]
                   for (x, c), (y, d) in zip(candidate_stores, candidate_stores[1:])):
            continue
        pairs.append(((first['op'], a), (second['op'], b)))
    if not pairs:
        return []
    context = _blank(header + '\n' + source)
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if re.search(r'(?m)^\s*#\s*undef\s+M2C_FIELD\b', context):
        return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    out = []
    for first in FIELD.finditer(part.clean, part.opening + 1, end - 1):
        second = FIELD.match(part.clean, first.end(), end - 1)
        if not second or first['indent'] != second['indent'] or first['base'] != second['base']:
            continue
        if part.clean[part.opening + 1:first.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        a = (TYPES[first['type']][0], integer(first['offset']))
        b = (TYPES[second['type']][0], integer(second['offset']))
        if (b, a) not in pairs:
            continue
        used = {first['base'], first['type'], second['type'], first['value'], second['value'], 's8', 'void', 'int'}
        if macros & used:
            continue
        valid = True
        for typ in {first['type'], second['type'], 's8'}:
            expected = TYPES[typ][1]
            aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
            if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
                valid = False
                break
        if not valid:
            continue
        # An ordinary pointer local/formal and ordinary integer inputs make
        # both addresses and values stable across this adjacent store pair.
        base = re.escape(first['base'])
        function = part.clean[span[0]:part.opening]
        local = part.clean[part.opening + 1:first.start()]
        body = part.clean[part.opening + 1:end - 1]
        if (not re.search(r'(?:\(|,)\s*void\s*\*\s*' + base + r'\s*[,)]', function)
                and not re.search(r'(?m)^\s*void\s*\*\s*' + base + r'\s*;', local)):
            continue
        if re.search(r'(?<!&)\&\s*\(*\s*' + base + r'\b', body):
            continue
        for value in (first['value'], second['value']):
            if re.fullmatch(NUMBER, value):
                continue
            scalar = r'(?P<type>s32|u32|int|unsigned\s+int)\s+' + re.escape(value)
            declared = (re.search(r'(?:\(|,)\s*' + scalar + r'\s*[,)]', function)
                        or re.search(r'(?m)^\s*' + scalar + r'\s*;', local))
            if not declared or re.search(r'(?<!&)\&\s*\(*\s*' + re.escape(value) + r'\b', body):
                valid = False
                break
            typ = declared['type']
            if typ in TYPES:
                aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
                if typ in macros or len(aliases) != 1 or not re.fullmatch(TYPES[typ][1], aliases[0].strip()):
                    valid = False
                    break
        if not valid:
            continue
        # Keep comments in place rather than moving or silently deleting them.
        atext, btext = source[first.start():first.end()], source[second.start():second.end()]
        if '/*' in atext + btext or '//' in atext + btext:
            continue
        out.append((FAMILY, edit(source, [(first.start(), second.end(), btext + atext)])))
        if len(out) == 4:
            break
    return out
