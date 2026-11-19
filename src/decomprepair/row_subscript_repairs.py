"""A table of fixed-size records addressed by subscript, where m2c added the scaled index to the base.

gcc 2.7.2 builds `base[i]` as `(i * size) + base` and `base + i * size` the other way round, and the operand order
survives to the `addu`: an N64 function at 99.7% was off by exactly that, `addu $v1, $v1, $a0` for the game's
`addu $v1, $a0, $v1`. m2c writes `temp = arg0 * 0x68; p = D + temp; ... M2C_FIELD(temp + D, s8 *, 0x61)`; written
as rows of bytes, `((u8 (*)[0x68]) D)[arg0][0]` and `((s8 (*)[0x68]) D)[arg0][0x61]`, it was exact, with no record
type to infer. Each access through the scaled index becomes a subscript of the row; the pointer and the index
temporary go when nothing else reads them.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'row_subscript'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4}


def _row(kind, base, index, size, offset):
    width = WIDTH.get(kind.split()[-1], 1)
    if width == 1 or (offset % width == 0 and size % width == 0):
        return f'(({kind} (*)[{size // width:#x}]) {base})[{index}][{offset // width:#x}]'
    return f'*({kind} *) &((u8 (*)[{size:#x}]) {base})[{index}][{offset:#x}]'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = source[opening:end]
    result = []
    for scale in re.finditer(r'(?m)^[ \t]*(?P<t>' + IDENT + r')\s*=\s*(?P<i>' + IDENT + r')\s*\*\s*(?P<k>' + NUMBER
                             + r')\s*;[ \t]*\n', body):
        temp, index, size = scale['t'], scale['i'], int(scale['k'], 0)
        if size < 2:
            continue
        text = body
        base_pattern = r'\(*\s*(?P<b>' + IDENT + r')\s*\)*'
        sums = (r'\(\s*' + re.escape(temp) + r'\s*\+\s*' + base_pattern + r'\s*\)',
                r'\(\s*' + base_pattern + r'\s*\+\s*' + re.escape(temp) + r'\s*\)')
        # M2C_FIELD((temp + B), T *, off) and *(T *)(temp + B)
        for pattern in sums:
            text = re.sub(r'M2C_FIELD\(\s*' + pattern + r'\s*,\s*(?P<kind>' + IDENT + r'(?:\s+' + IDENT
                          + r')?)\s*\*\s*,\s*(?P<off>' + NUMBER + r')\s*\)',
                          lambda m, i=index, k=size: _row(m['kind'], m['b'], i, k, int(m['off'], 0)), text)
        # a pointer: p = B + temp, p = temp + B, or the permuter's split `p = (char *)(B); p += (s32)(temp);`
        cast = r'(?:\(\s*[\w ]+\*\s*\)\s*)?'
        wrapped = r'\(*\s*(?P<b>' + IDENT + r')\s*\)*'
        forms = (r'(?P<p>' + IDENT + r')\s*=\s*' + cast + r'\(*\s*' + re.escape(temp) + r'\s*\+\s*' + wrapped + r'\s*;',
                 r'(?P<p>' + IDENT + r')\s*=\s*' + cast + r'\(*\s*(?P<b>' + IDENT + r')\s*\+\s*' + re.escape(temp)
                 + r'\s*\)*\s*;',
                 r'(?P<p>' + IDENT + r')\s*=\s*' + cast + wrapped + r'\s*;\s*(?P=p)\s*\+=\s*(?:\(\s*s32\s*\)\s*)?\(*\s*'
                 + re.escape(temp) + r'\s*\)*\s*;')
        pointers = []
        for form in forms:
            for assign in re.finditer(r'(?m)^[ \t]*' + form + r'[ \t]*\n', text):
                declared = re.search(r'(?m)^[ \t]*(?P<kind>(?:unsigned\s+|signed\s+)?' + IDENT + r')\s*\*\s*'
                                     + assign['p'] + r'\s*;', text)
                if declared:
                    pointers.append((assign, assign['b'], declared['kind']))
        pointers.sort(key=lambda item: item[0].start())
        for assign, base, kind in reversed(pointers):
            p = assign['p']
            rest = text[assign.end():]
            rest = re.sub(r'M2C_FIELD\(\s*' + p + r'\s*,\s*(?P<kind>' + IDENT + r')\s*\*\s*,\s*(?P<off>' + NUMBER
                          + r')\s*\)', lambda m, b=base, i=index, k=size: _row(m['kind'], b, i, k, int(m['off'], 0)), rest)
            rest = re.sub(r'(?<![\w.>])' + p + r'\s*\[\s*(?P<off>' + NUMBER + r')\s*\]',
                          lambda m, t=kind, b=base, i=index, k=size: _row(t, b, i, k, int(m['off'], 0)), rest)
            rest = re.sub(r'\*\s*' + p + r'(?![\w\[])', lambda m, t=kind, b=base, i=index, k=size: _row(t, b, i, k, 0), rest)
            if re.search(r'(?<![\w.>])' + p + r'\b', rest):
                continue  # still used some other way: keep it
            text = text[:assign.start()] + rest
            text = re.sub(r'(?m)^[ \t]*(?:unsigned\s+|signed\s+)?' + IDENT + r'\s*\*\s*' + p + r'\s*;[ \t]*\n', '', text,
                          count=1)
        if text == body:
            continue
        # the index temporary goes once nothing reads it
        declaration = re.compile(r'(?m)^[ \t]*[\w ]+?\s+' + temp + r'\s*;[ \t]*\n')
        if not re.search(r'(?<![\w.>])' + temp + r'\b', declaration.sub('', text.replace(scale.group(0), ''))):
            text = text.replace(scale.group(0), '', 1)
            text = re.sub(r'(?m)^[ \t]*[\w ]+?\s+' + temp + r'\s*;[ \t]*\n', '', text, count=1)
        candidate = source[:opening] + text + source[end:]
        if candidate != source and candidate not in [t for _, t in result]:
            result.append((FAMILY, candidate))
    return result
