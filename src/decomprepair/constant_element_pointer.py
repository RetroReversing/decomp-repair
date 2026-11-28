"""A call that reads several members of one constant-index record, given a pointer to that record.

    draw(items[2].name, items[2].x, items[2].y);      ->      {
                                                                  Item *element = &items[2];
                                                                  draw(element->name, element->x, element->y);
                                                              }

The compiler folds `items[2].x` into an offset from `items`. A game that took the record's address first reads the
members off that one address, and in a loop keeps `items + 2` in a saved register of its own, which also moves every
register chosen after it. A 437-instruction N64 menu routine (SN GCC 2.8.1) went 3020 -> 0 with two such records
(4040 -> 870 on the draft without its other edit). `element_pointer_direct_index` is the other direction.

Only a call written as a statement of its own, whose arguments have no call, assignment, `++` or `--`, and only for a
constant index other than 0 read through two members or more, so the address and the reads give the same values in
either spelling. One child rewrites every such record of the function, then one per record."""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'constant_element_pointer'
FAMILIES = (FAMILY,)
LIMIT = 6
CALL = re.compile(r'(?<=[;{}])\s*(?P<callee>[A-Za-z_]\w*)\s*\(')
ELEMENT = re.compile(r'(?<![\w.>])(?P<array>[A-Za-z_]\w*)\s*\[\s*(?P<index>0[xX][0-9a-fA-F]+|[1-9]\d*)\s*\]\s*\.\s*')
UNSAFE = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|\b(?!sizeof\b)[A-Za-z_]\w*\s*\(|\)\s*\(')
KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof'}
NOT_A_TYPE = {'return', 'else', 'void', 'goto', 'case', 'sizeof'}


def _declared(text, array, before, after):
    """The element types `text` declares `array` with, as a pointer (`T *array`) or an array (`T array[...]`)."""
    pattern = (rf'{before}\s*(?:(?:static|extern|const)\s+)*(?P<type>(?:struct\s+)?[A-Za-z_]\w*)'
               rf'(?:\s*(?P<star>\*)\s*|\s+){array}\b(?P<brackets>(?:\s*\[[^\][]*\])?)\s*{after}')
    return [(hit['type'], hit.start()) for hit in re.finditer(pattern, text)
            if bool(hit['star']) != bool(hit['brackets']) and hit['type'] not in NOT_A_TYPE]


def _file_scope(text):
    """`text` with everything inside braces blanked: a struct's member or another function's local is not a global."""
    out, at = [], 0
    while True:
        opening = text.find('{', at)
        closing = close(text, opening) if opening >= 0 else -1
        if closing < 0:
            out.append(text[at:])
            return ''.join(out)
        out.append(text[at:opening] + ';')
        at = closing + 1


def _record_type(clean, header, span, array):
    """The element type of `array` as this function sees it: its parameters and locals first, then the globals. A
    prototype's parameter of the same name says nothing about it; two different types give none."""
    function = clean[span[0]:span[1]]
    opening = function.find('(')
    closing = close(function, opening, '(', ')')
    parameters = ',' + function[opening + 1:closing] + ','
    found = _declared(parameters, array, ',', '(?=,)')
    found += _declared(function[closing + 1:], array, '(?<=[;{}])', '(?=[;=,])')
    if not found:
        local = rf'(?<=[;{{}}])\s*(?!return\b)[A-Za-z_]\w*[\s*]+(?:[^;{{}}()=]*[,*\s])?{array}\b\s*[,;=\[]'
        if re.search(rf'\b{array}\b', parameters) or re.search(local, function[closing + 1:]):
            return None  # declared here in a form not read: no global stands in for it
        outside = _file_scope(';' + _blank(header) + '\n;' + clean[:span[0]])
        found = _declared(outside, array, '(?<=;)', '(?=[;=])')
    kinds = {kind for kind, _ in found}
    return kinds.pop() if len(kinds) == 1 else None


def _sites(clean, header, span, context):
    """[(start, end, {(array, index): type})] of the call statements that read a constant record twice or more."""
    sites = []
    for call in CALL.finditer(clean, span[0], span[1]):
        if call['callee'] in KEYWORDS or re.search(rf'#[ \t]*define[ \t]+{call["callee"]}\(', context):
            continue
        opening = call.end() - 1
        closing = close(clean, opening, '(', ')')
        if closing < 0:
            continue
        end = re.compile(r'\s*;').match(clean, closing + 1)
        arguments = clean[opening + 1:closing]
        if not end or UNSAFE.search(arguments):
            continue
        counts = {}
        for hit in ELEMENT.finditer(arguments):
            key = (hit['array'], int(hit['index'], 0))
            counts[key] = counts.get(key, 0) + 1
        found = {}
        for key, count in counts.items():
            kind = _record_type(clean, header, span, key[0]) if count > 1 and key[1] else None
            if kind:
                found[key] = kind
        if found:
            sites.append((call.start('callee'), end.end(), found))
    return sites


def _rewrite(source, context, sites, wanted):
    taken = set(re.findall(r'[A-Za-z_]\w*', context))
    out = source
    for start, end, found in reversed(sites):
        keys = [key for key in found if key in wanted]
        if not keys:
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        statement = source[start:end]
        declarations, number = [], 1
        for array, index in keys:
            pointer = 'element'
            while pointer in taken or any(f' *{pointer} =' in line for line in declarations):
                number += 1
                pointer = f'element{number}'

            def member(hit, array=array, index=index, pointer=pointer):
                if hit['array'] == array and int(hit['index'], 0) == index:
                    return f'{pointer}->'
                return hit[0]

            statement = ELEMENT.sub(member, statement)
            declarations.append(f'{found[(array, index)]} *{pointer} = &{array}[{index}];')
        lines = ''.join(f'{indent}    {line}\n' for line in declarations)
        out = out[:start] + f'{{\n{lines}{indent}    {statement}\n{indent}}}' + out[end:]
    return out


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    if re.search(r'^[ \t]*#|\b(?:asm|__asm__|volatile)\b', clean[span[0]:span[1]], re.M):
        return []
    context = header + '\n' + source
    sites = _sites(clean, header, span, context)
    keys = list(dict.fromkeys(key for _, _, found in sites for key in found))
    if not keys:
        return []
    wanted = [set(keys)] + ([{key} for key in keys] if len(keys) > 1 else [])
    out = [_rewrite(source, context, sites, each) for each in wanted]
    return [(FAMILY, text) for text in dict.fromkeys(out) if text != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 66}
