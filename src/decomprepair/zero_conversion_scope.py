"""Preserve a known zero through a narrow conversion for MIPS allocation.

Both operands read the same already-loaded integer local and are equal in the
low 16 bits.  This can retain a separate lifetime through GCC's early passes.
"""
import re

from .csource import _blank, find

FAMILY = 'zero_conversion_scope'
_ID = r'[A-Za-z_]\w*'


def variants(source, name, arch='mips'):
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean, re.M):
        return []
    body = clean[opening + 1:closing]
    # A plain local, assigned immediately from a pointer, has one stable value.
    # The following scoped comparison is the motivating allocation shape.
    pattern = (rf'(?:^|[;{{}}])\s*(?P<value>{_ID})\s*=\s*\*\s*{_ID}\s*;\s*'
               rf'(?P<zero>{_ID})\s*=\s*0\s*;\s*do\s*\{{\s*{_ID}\s*=\s*'
               rf'(?:\({_ID}\)\s*)?\(\s*(?P=zero)\s*<\s*(?P=value)\s*\)\s*;\s*\}}\s*while\s*\(\s*0\s*\)\s*;')
    out = []
    for hit in re.finditer(pattern, body):
        value, zero = hit['value'], hit['zero']
        if value == zero:
            continue
        for var in (value, zero):
            declarations = list(re.finditer(
                rf'(?:^|[;{{}}])\s*(?:s32|u32|int|long|unsigned\s+int)\s+{re.escape(var)}\s*;', body))
            if len(declarations) != 1 or declarations[0].end() > hit.start():
                break
            prefix = body[:declarations[0].start()]
            if prefix.count('{') != prefix.count('}'):
                break  # only unshadowed function-scope locals
            if re.search(rf'&\s*{re.escape(var)}\b', body):
                break
        else:
            start = opening + 1 + hit.start('zero')
            end = opening + 1 + hit.end('zero')
            tail = re.match(r'\s*=\s*0\s*;', clean[end:])
            replacement = (f'{zero} = (unsigned short) {value} ^ '
                           f'((unsigned int) {value} & 0xFFFF);')
            out.append((FAMILY, source[:start] + replacement + source[end + tail.end():]))
    return out[:8]
