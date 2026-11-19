"""A table element's index computed before a call, the element itself read through the table after it.

m2c turns `old = table[i]; table[i] = v;` around a call into a pointer computed before the call,

    temp_s0 = ((arg0 & 0xF) * 2) + D_80112EBE;
    func_8008C0D4();
    temp_s1 = *temp_s0;
    *temp_s0 = arg1;

which keeps the whole address in a saved register. The game kept only the index (`andi $s0, $a0, 0xF` before the
call) and formed the address after it: an N64 function was 89% so and exact as `__repair_index = arg0 & 0xF;` and
`((u16 *) D_80112EBE)[__repair_index]` at each use. Offered when the pointer is only dereferenced, its element size
is the multiplier, a call comes before its first use, and nothing the index reads is assigned in between.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'pointer_index_after_call'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
SIZES = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2, 'u32': 4, 's32': 4, 'int': 4, 'f32': 4,
         'float': 4}


def _assigned(name, text):
    return re.search(r'(?<![\w.>])' + re.escape(name) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*'
                     + re.escape(name) + r'\b|\b' + re.escape(name) + r'\s*(?:\+\+|--)', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '__repair_index' in clean:
        return []
    result = []
    for decl in re.finditer(r'(?m)^[ \t]*(?:(?:unsigned|signed)\s+)?(?P<elem>' + IDENT + r')\s*\*\s*(?P<ptr>' + IDENT
                            + r')\s*;[ \t]*\n', clean[opening:end]):
        elem, ptr = decl['elem'], decl['ptr']
        size = SIZES.get(elem)
        if size is None:
            continue
        assign = re.compile(r'(?m)^(?P<indent>[ \t]*)' + re.escape(ptr) + r'\s*=\s*\(\s*\((?P<index>[^;]*?)\)\s*\*\s*(?P<k>\d+|0x[0-9a-fA-F]+)\s*\)'
                            r'\s*\+\s*(?P<sym>' + IDENT + r')\s*;[ \t]*\n').search(clean, opening, end)
        if not assign or int(assign['k'], 0) != size \
                or len(re.findall(r'(?<![\w*.>])' + re.escape(ptr) + r'\s*=(?!=)', clean[opening:end])) != 1:
            continue
        after = clean[assign.end():end]
        uses = [m for m in re.finditer(r'(?<![\w.>])' + re.escape(ptr) + r'\b', after)]
        if not uses or any(after[max(0, m.start() - 1)] != '*' for m in uses):
            continue  # only `*ptr`
        first = assign.end() + uses[0].start()
        if not re.search(IDENT + r'\s*\(', clean[assign.end():first]):
            continue  # no call before the first use
        index = source[assign.start('index'):assign.end('index')]
        names = set(re.findall(r'(?<![\w.])' + IDENT, re.sub(r'\b0[xX][0-9a-fA-F]+\b', '', index)))
        if re.search(IDENT + r'\s*\(|\+\+|--', index) or any(_assigned(n, after) for n in names):
            continue
        element = f"(({elem} *) {assign['sym']})[__repair_index]"
        tail = re.sub(r'\*\s*' + re.escape(ptr) + r'\b', element, source[assign.end():end])
        text = (source[:opening + decl.start()] + f"{decl.group(0)[:len(decl.group(0)) - len(decl.group(0).lstrip())]}"
                f"s32 __repair_index;\n" + source[opening + decl.end():assign.start()]
                + f"{assign['indent']}__repair_index = {index};\n" + tail + source[end:])
        result.append((FAMILY, text))
    return result[:2]
