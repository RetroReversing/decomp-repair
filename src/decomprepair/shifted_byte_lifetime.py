"""Stage a shifted byte through an initialized, identical-arm guard.

GCC 2.7.2 can give the two loads feeding a product opposite registers when a
shifted byte is added afterwards. Keeping that byte in a local and testing a
bit cleared by its shift changes allocation even though the guard disappears.
The two arms read the same ordinary member once; the added guard has no effect
on the program's values. The judge decides whether the shape helps.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shifted_byte_lifetime'
FAMILIES = (FAMILY,)
_IDENT = r'[A-Za-z_]\w*'
_BYTE = rf'\(\(u8\s*\*\)\s*(?P<array>{_IDENT})\)\s*\[\s*(?P<index>\d+)\s*\]'
_PATTERN = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<dst>{_IDENT})\s*=\s*'
    rf'\(\(u32\)\s*\(\s*{_BYTE}\s*\*\s*'
    rf'(?P<base>{_IDENT})->(?P<factor>{_IDENT})\s*\)\s*\)\s*>>\s*(?P<rshift>\d+)\s*;\s*\n'
    rf'[ \t]*(?P=dst)\s*\+=\s*\(\(u8\s*\*\)\s*(?P=array)\)\s*\[\s*(?P<high_index>\d+)\s*\]'
    rf'\s*<<\s*(?P<lshift>\d+)\s*;\s*\n'
    rf'[ \t]*(?P<other>{_IDENT})\s*=\s*(?P=array)->(?P<field>{_IDENT})\s*;'
)


def variants(source, name, header=""):
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', source + '\n' + header, re.M):
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for m in _PATTERN.finditer(clean, opening, end):
        if not (0 < int(m['lshift']) < 24 and 0 < int(m['rshift']) < 32):
            continue
        # Assignments must be ordinary unsigned locals, not fields or aliases.
        body = clean[opening:m.start()]
        if not all(re.search(rf'\bu32\s+{re.escape(v)}\s*;', body) for v in (m['dst'], m['other'])):
            continue
        if m['dst'] == m['other'] or re.search(rf'&\s*\b(?:{m["dst"]}|{m["other"]})\b', clean[opening:end]):
            continue
        local = '__repair_shifted_byte'
        if re.search(rf'\b{local}\b', clean[opening:end]):
            continue
        i = m['indent']
        byte = f'((u8 *) {m["array"]})[{m["index"]}]'
        high = f'((u8 *) {m["array"]})[{m["high_index"]}]'
        field = f'{m["array"]}->{m["field"]}'
        replacement = (f'{i}{{\n{i}    u32 {local} = {high} << {m["lshift"]};\n'
                       f'{i}    {m["dst"]} = ((u32) ({m["base"]}->{m["factor"]} * {byte})) >> {m["rshift"]};\n'
                       f'{i}    {m["dst"]} += {local};\n'
                       f'{i}    if ({local} & 1) {m["other"]} = {field};\n'
                       f'{i}    else {m["other"]} = {field};\n{i}}}')
        out.append((FAMILY, source[:m.start()] + replacement + source[m.end():]))
    return out
