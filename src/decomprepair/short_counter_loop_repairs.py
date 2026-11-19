"""m2c's shifted halfword counter, as the `s16` loop counter it was.

A loop over a `short` counter comes back from m2c as the shifts gcc used to sign-extend it:

    var_s0 = 0;
    var_a0 = 0 << 0x10;
    do {
        f(var_a0 >> 0x10, 2);
        temp_v0 = var_s0 + 1;
        var_s0 = temp_v0;
        var_a0 = var_s0 << 0x10;
    } while (temp_v0 < 4);

An N64 function was 95.4% so and exact as `for (i = 0; i < 4; i++) { f(i, 2); }` with `i` the `s16` m2c declared.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'short_counter_loop'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
SHAPE = re.compile(
    r'(?m)^(?P<ind>[ \t]*)(?P<shift>' + I + r')\s*=\s*(?P<start>\d+)\s*<<\s*0x10;[ \t]*\n'
    r'(?P<between>(?:[ \t]*[^\n;{}]*;[ \t]*\n)*?)'
    r'[ \t]*do\s*\{[ \t]*\n(?P<body>(?:[ \t]*[^\n{}]*;[ \t]*\n)*?)'
    r'[ \t]*(?P<temp>' + I + r')\s*=\s*(?P<count>' + I + r')\s*\+\s*1;[ \t]*\n'
    r'[ \t]*(?P=count)\s*=\s*(?P=temp);[ \t]*\n'
    r'[ \t]*(?P=shift)\s*=\s*(?P=count)\s*<<\s*0x10;[ \t]*\n'
    r'[ \t]*\}\s*while\s*\(\s*(?P=temp)\s*<\s*(?P<limit>[^)]+)\);[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        temp, shift, count = hit['temp'], hit['shift'], hit['count']
        if not re.search(r'\b(?:s16|short)\s+' + temp + r'\s*;', clean[opening:end]):
            continue
        body = source[hit.start('body'):hit.end('body')]
        if re.search(r'\b(?:' + temp + '|' + count + r')\b', body):
            continue
        body = re.sub(r'\(\s*' + shift + r'\s*>>\s*0x10\s*\)|\b' + shift + r'\s*>>\s*0x10', temp, body)
        if re.search(r'\b' + shift + r'\b', body):
            continue
        ind = hit['ind']
        between = source[hit.start('between'):hit.end('between')]
        # the counter's own `count = 0;` before the loop goes; anything else stays before it
        before = clean[opening:hit.start()]
        init = list(re.finditer(r'(?m)^[ \t]*' + count + r'\s*=\s*' + hit['start'] + r'\s*;[ \t]*\n', before))
        loop = (between + f'{ind}for ({temp} = {hit["start"]}; {temp} < {hit["limit"].strip()}; {temp}++) {{\n'
                + body + f'{ind}}}\n')
        text = source[:hit.start()] + loop + source[hit.end():]
        if init:
            a, b = opening + init[-1].start(), opening + init[-1].end()
            text = text[:a] + text[b:]
        result.append((FAMILY, text))
    return result[:2]
