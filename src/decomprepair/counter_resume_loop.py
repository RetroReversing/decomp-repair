"""A second loop that carries on from the first loop's counter, written as the resumed loop.

An agent (and m2c's masked spelling) writes a loop that continues where another stopped as a loop over a fresh masked
copy:

    k = i & 0xFF;
    while (k < 200) {           // or `for (k = i & 0xFF; k < 200; k = (k + 1) & 0xFF)`
        ... k ...
        k = (k + 1) & 0xFF;
    }

The game's source stepped the first loop's counter itself and masked it again at each use, so the compiler keeps one
register for both loops and copies the masked value at the loop head (`andi; move`):

    while ((i & 0xFF) < 200) {
        k = i & 0xFF;
        ... k ...
        i++;
    }

Only when neither the counter nor the copy is read after the loop and the body assigns neither, so the values are the
same. Two companions of the same match are offered combined with it, since each alone scores worse than the start:
the counter declared at the mask's width (`u8 i;`, every read of it already masked), and m2c's scaled sum
`(k * 4) + k` written `k * 5`. A 61-instruction N64 table fill (KMC GCC 2.7.2) went 180 -> 5 with the three.
Labels `counter_resume_loop`.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILIES = ('counter_resume_loop',)
MASK = r'(?:0[xX][fF]{2}(?:[fF]{2})?|255|65535)'
WIDTH = {255: 'u8', 65535: 'u16'}
HEAD = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?:'
    rf'(?P<k>{IDENT})\s*=\s*(?P<i>{IDENT})\s*&\s*(?P<mask>{MASK})\s*;\s*while\s*\(\s*(?P=k)\s*<\s*(?P<limit>[^;()]+?)\s*\)'
    rf'|for\s*\(\s*(?P<fk>{IDENT})\s*=\s*(?P<fi>{IDENT})\s*&\s*(?P<fmask>{MASK})\s*;\s*(?P=fk)\s*<\s*(?P<flimit>[^;()]+?)\s*;'
    rf'\s*(?P=fk)\s*=\s*\(\s*(?P=fk)\s*\+\s*1\s*\)\s*&\s*{MASK}\s*\)'
    r')\s*{')


def _uses(text, name):
    return re.search(r'(?<![\w.>])' + name + r'\b', text)


def _writes(text, name):
    return re.search(r'(?<![\w.>])' + name + r'\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--|&)\s*' + name + r'\b'
                     r'(?!\s*(?:&|\)\s*[<>]))', text)


def _after_declarations(body):
    """The offset in a block's inside where its first statement starts (C89 declarations come first)."""
    at = 0
    declaration = re.compile(r'\s*(?!return\b|goto\b)(?:(?:const|volatile|unsigned|signed|struct|union)\s+)*'
                             + IDENT + r'(?:\s+|\s*\*+\s*)' + IDENT + r'(?:\s*\[[^\]]*\])?\s*;')
    while True:
        hit = declaration.match(body, at)
        if not hit:
            return at
        at = hit.end()


def _resumed(source, name):
    """[(source with one loop resumed, counter, mask value, copy)]."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for head in HEAD.finditer(clean, opening, end):
        in_for = head['fk'] is not None
        k, i = head['fk'] or head['k'], head['fi'] or head['i']
        mask, limit = head['fmask'] or head['mask'], head['flimit'] or head['limit']
        brace = head.end() - 1
        stop = close(clean, brace, '{', '}')
        if not stop or k == i or _uses(clean[stop:end], k) or _uses(clean[stop:end], i):
            continue
        inner = clean[brace + 1:stop - 1]
        if in_for:
            if re.search(r'\bcontinue\b', inner):
                continue
            tail = len(inner.rstrip())
        else:
            step = re.search(rf'(?<![\w.>]){k}\s*=\s*\(\s*{k}\s*\+\s*1\s*\)\s*&\s*{MASK}\s*;\s*$', inner)
            if not step or inner[:step.start()].rstrip()[-1:] not in ('', ';', '}', '{'):
                continue
            tail = step.start()
        if _writes(inner[:tail], k) or _writes(inner[:tail], i):
            continue
        indent = head['indent']
        step_indent = indent + '    '
        raw = source[brace + 1:stop - 1]
        first = _after_declarations(inner[:tail])
        rest = raw[first:tail].rstrip()
        body = (raw[:first].rstrip() + f'\n{step_indent}{k} = {i} & {mask};' + rest
                + f'\n{step_indent}{i}++;\n{indent}')
        loop = f'{indent}while (({i} & {mask}) < {limit}) {{{body}}}'
        result.append((source[:head.start()] + loop + source[stop:], i, int(mask, 0), k))
    return result


def _narrowed(source, name, counter, value):
    """`s32 i;` as `u8 i;` when every read of it is already masked to that width."""
    span = find(source, name)
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}')
    declaration = re.search(r'(?m)^[ \t]*(s32|u32|int|unsigned int)\s+' + counter + r'\s*;', clean[opening:end])
    if value not in WIDTH or not declaration:
        return None
    body = clean[opening:opening + declaration.start()] + clean[opening + declaration.end():end]
    mask = rf'(?:0[xX]{value:X}|0[xX]{value:x}|{value})\b'
    allowed = (rf'(?<![\w.>]){counter}\s*&\s*{mask}', rf'\(\s*{WIDTH[value]}\s*\)\s*{counter}\b',
               rf'(?<![\w.>]){counter}\s*(?:\+\+|\+=\s*1\s*;|=\s*0\s*;)')
    for pattern in allowed:
        body = re.sub(pattern, '', body)
    if _uses(body, counter):
        return None
    start, stop = opening + declaration.start(1), opening + declaration.end(1)
    return source[:start] + WIDTH[value] + source[stop:]


def _scaled(source, copy):
    """m2c's `(k * 4) + k` as `k * 5`."""
    def merged(hit):
        return f'{copy} * {int(hit[1]) + 1}'

    return re.sub(rf'\(\s*{copy}\s*\*\s*(\d+)\s*\)\s*\+\s*{copy}\b(?!\s*[*/.\[(-])', merged, source)


def variants(source, name):
    result, seen = [], {source}
    for resumed, counter, value, copy in _resumed(source, name):
        narrow = _narrowed(resumed, name, counter, value)
        children = [resumed, narrow, _scaled(narrow or resumed, copy), _scaled(resumed, copy)]
        for child in children:
            if child and child not in seen:
                seen.add(child)
                result.append(('counter_resume_loop', child))
    return result[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
