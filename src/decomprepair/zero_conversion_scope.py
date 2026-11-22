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
    pattern = (rf'(?:^|[;{{}}])\s*(?P<value>{_ID})\s*=\s*\*\s*(?P<pointer>{_ID})\s*;\s*'
               rf'(?P<zero>{_ID})\s*=\s*(?P<expr>0|(?:\(u16\)|\(unsigned\s+short\))\s*(?P=value)\s*\^\s*\(\s*(?:(?:\(u32\)|\(unsigned\s+int\))\s*)?(?P=value)\s*&\s*0[xX][fF]{{4}}\s*\))\s*;\s*do\s*\{{\s*{_ID}\s*=\s*'
               rf'(?:\({_ID}\)\s*)?\(\s*(?P=zero)\s*<\s*(?P=value)\s*\)\s*;\s*\}}\s*while\s*\(\s*0\s*\)\s*;')
    out = []
    for hit in re.finditer(pattern, body):
        value, zero = hit['value'], hit['zero']
        if value == zero:
            continue
        for var in (value, zero):
            declarations = list(re.finditer(
                rf'(?:^|[;{{}}])\s*(?:s32|u32|int|long|unsigned\s+int)\s+{re.escape(var)}\s*;', body))
            shadows = re.findall(rf'(?:^|[;{{}}])\s*(?:(?:const|volatile|unsigned|signed|struct)\s+)*{_ID}\s+{re.escape(var)}\s*(?:[;=\[])', body)
            if len(shadows) != 1 or len(declarations) != 1 or declarations[0].end() > hit.start():
                break
            prefix = body[:declarations[0].start()]
            if prefix.count('{') != prefix.count('}'):
                break  # only unshadowed function-scope locals
            if re.search(rf'&\s*\(*\s*{re.escape(var)}\b', body):
                break
        else:
            start = opening + 1 + hit.start('zero')
            expr_end = opening + 1 + hit.end('expr')
            if hit['expr'] == '0':
                replacement = (f'{zero} = (unsigned short) {value} ^ '
                               f'((unsigned int) {value} & 0xFFFF)')
                out.append((FAMILY, source[:start] + replacement + source[expr_end:]))
            pointer = hit['pointer']
            # The load has already evaluated this local pointer. Its pointee may
            # be volatile, but the pointer itself must be an unescaped local.
            decl = list(re.finditer(rf'(?:^|[;{{}}])\s*(?:volatile\s+)?(?:s32|u32|int|long|unsigned\s+int)\s*\*\s*{pointer}\s*;', body))
            shadows = re.findall(rf'(?:^|[;{{}}])\s*(?:(?:const|volatile|unsigned|signed|struct)\s+)*{_ID}\s*\**\s*{pointer}\s*(?:[;=\[])', body)
            if len(shadows) != 1 or len(decl) != 1 or decl[0].end() > hit.start() or re.search(rf'&\s*\(*\s*{pointer}\b', body):
                continue
            prefix = body[:decl[0].start()]
            if prefix.count('{') != prefix.count('}'):
                continue
            replacement = (f'{zero} = (unsigned short) (unsigned int) {pointer} ^ '
                           f'((unsigned int) {pointer} & 0xFFFF)')
            out.append((FAMILY, source[:start] + replacement + source[expr_end:]))
    return out[:8]
