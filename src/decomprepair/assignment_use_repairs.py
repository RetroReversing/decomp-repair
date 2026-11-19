"""An assignment m2c wrote where the value was first available, written where it is first used.

m2c puts each temporary's assignment at the instruction that computed it; the source often had it at the use, and
gcc 2.7.2 keeps that order where a load can't pass a store through a cast pointer, or where a value assigned inside
a call's arguments is computed with them. Two N64 functions matched so, each 98-99% before:

    temp_a0 = *(s32 *)((char *)arg0 + 0);       ...stores through arg0...
    (stores)                                     temp_a0 = *(s32 *)((char *)arg0 + 0);
    if (temp_a0) { ... }                         if (temp_a0) { ... }

    temp_s1 = arg1 + arg3;
    g(temp_s0 + D, temp_s1);                     g(temp_s0 + D, temp_s1 = arg1 + arg3);

Offered: the assignment moved to just before the statement that first uses it, and written into that use. A
hypothesis: what lies between may change the value (a store through an aliasing pointer), which the judge settles.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'assignment_at_use'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
ASSIGN = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<var>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;{}]+);[ \t]*\n')


def _assigned(name, text):
    return re.search(r'(?<![\w.>])' + name + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + name + r'\b|\b'
                     + name + r'\s*(?:\+\+|--)|&\s*' + name + r'\b', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    declared = set(re.findall(r'(?m)^[ \t]*(?:register\s+)?(?:[\w ]+?)[\s*]+(' + IDENT + r')\s*;', body))
    result = []
    for hit in ASSIGN.finditer(clean, opening + 1, end):
        var, value = hit['var'], hit['value']
        if var not in declared or re.search(IDENT + r'\s*\(', value) or re.search(r'\b' + var + r'\b', value):
            continue
        # the next statements of the same block, until the first that mentions the variable
        line_start = hit.end()
        use = None
        for line in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<text>[^\n]*)\n', clean[line_start:end]):
            text = line['text']
            if not text.strip():
                continue
            if len(line['indent']) < len(hit['indent']) or text.lstrip().startswith('}'):
                break
            if re.search(r'\b' + var + r'\b', text):
                if len(line['indent']) == len(hit['indent']):
                    use = (line_start + line.start(), line_start + line.end(), text)
                break
            if len(line['indent']) != len(hit['indent']) or re.search(r'\b(?:goto|return|case|default)\b|^\w+:', text):
                use = None
                break
        if not use:
            continue
        between = clean[hit.end():use[0]]
        names = set(re.findall(r'(?<![\w.>])' + IDENT, re.sub(r'\b0[xX][0-9a-fA-F]+\b', '', value))) - {'char', 's32'}
        if any(_assigned(n, between) for n in names | {var}):
            continue
        statement = source[hit.start():hit.end()]
        if between.strip():
            moved = source[:hit.start()] + source[hit.end():use[0]] + statement + source[use[0]:]
            result.append((FAMILY, moved))
        # written into the use: the first mention that's read, not stored to
        first = re.search(r'(?<![\w.>])' + var + r'\b(?!\s*=(?!=))', clean[use[0]:use[1]])
        if first:
            at = use[0] + first.start()
            text = (source[:hit.start()] + source[hit.end():at] + '(' + var + ' = ' + value.strip() + ')'
                    + source[at + len(var):])
            result.append((FAMILY, text))
        if len(result) >= 6:
            break
    return result[:6]
