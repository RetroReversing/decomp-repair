"""m2c's `while (1)` over a masked word counter, written as the narrow counter's `for` loop.

    i = 0;
    while (1) {                                 u8 i;
        x = i & 0xFF;                     ->    for (i = 0; i < 6; i++) {
        if (T[x] == 0) break;                       if (T[i] == 0) break;
        i++;                                    }
        if ((u32) (i & 0xFF) >= 6) break;       if (i < 3) ...
    }
    if (x < 3) ...

gcc rotates the `for` and keeps the narrowing in the back branch's delay slot, which m2c reads back as a second
variable holding the masked value. On a 97-instruction N64 state machine (KMC gcc 2.7.2, `-O1`) the `while` form was
440 and no other family moved it; the `for` over a `u8` counter was exact.

`masked_while_counter_for`: offered when the counter is set to 0 right before the `while (1)`, the body's last two
statements step it and break at `(i & MASK) >= N`, it is read only through the mask (spelled out, or by a helper that
returns its argument masked), and a local set from the mask at the head of the body is read after the loop only in
`x < K` or `x >= K` with `K < N` (at the loop's end it holds N - 1 where the counter holds N). The exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_while_counter_for'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0x[0-9A-Fa-f]+|\d+)'
MASKS = {0xFF: 'u8', 0xFFFF: 'u16'}
WHILE = re.compile(rf'\b(?P<counter>{IDENT})\s*=\s*0\s*;\s*while\s*\(\s*1\s*\)\s*\{{')
EXIT = re.compile(rf'(?<![\w.>])(?P<counter>{IDENT})\s*\+\+\s*;\s*if\s*\((?P<test>[^;{{}}]*)\)\s*'
                  r'(?:\{\s*break\s*;\s*\}|break\s*;)\s*$')
_CAST = re.compile(r'\(\s*(?:u32|s32|int|unsigned int)\s*\)')


def _bound(test, counter):
    """(mask, bound) of `(counter & MASK) >= bound`, however it is parenthesised and cast."""
    flat = re.sub(r'[\s()]', '', _CAST.sub('', test))
    hit = re.fullmatch(rf'{counter}&({NUM})>=({NUM})', flat)
    return (int(hit[1], 0), int(hit[2], 0)) if hit else (None, None)


def _helpers(clean):
    """{name: mask} of the helpers that only return their argument masked."""
    found = re.finditer(rf'\b({IDENT})\s*\(\s*{IDENT}\s+({IDENT})\s*\)\s*\{{\s*return\s+\2\s*&\s*({NUM})\s*;\s*\}}', clean)
    return {hit[1]: int(hit[3], 0) for hit in found}


def _masked(counter, mask, helpers):
    """A pattern for every spelling of the masked counter."""
    spelled = rf'\(\s*{counter}\s*\)|{counter}'
    number = rf'(?:0x{mask:X}|0x{mask:x}|{mask})\b'
    core = rf'(?:{spelled})\s*&\s*{number}'
    forms = [rf'\(\s*\(\s*(?:int|s32|u32)\s*\)\s*\(\s*{core}\s*\)\s*\)',
             rf'\(\s*(?:int|s32|u32)\s*\)\s*\(\s*{core}\s*\)', rf'\(\s*{core}\s*\)', core]
    forms += [rf'\b{name}\s*\(\s*{counter}\s*\)' for name, value in helpers.items() if value == mask]
    return '(?:' + '|'.join(forms) + ')'


def _declaration(body, name):
    return re.search(rf'(?<=[;{{}}])\s*(?:u8|u16|u32|s16|s32|int|unsigned int|unsigned short|unsigned char)\s+{name}\s*;',
                     body)


def _rewrite(source, clean, span, loop, helpers):
    counter = loop['counter']
    end = close(clean, loop.end() - 1, '{', '}')
    if end is None:
        return None
    inner = clean[loop.end():end - 1]
    stop = EXIT.search(inner)
    if not stop or stop['counter'] != counter:
        return None
    mask, bound = _bound(stop['test'], counter)
    if mask not in MASKS or not 0 < bound <= mask:
        return None
    body = source[loop.end():loop.end() + stop.start()]
    masked = _masked(counter, mask, helpers)
    head = re.match(rf'\s*({IDENT})\s*=\s*{masked}\s*;', body)
    copy = head[1] if head else None
    if head:
        body = body[head.end():]
    if re.search(r'\b(?:continue|goto)\b', body):
        return None
    body = re.sub(masked, counter, body)
    if copy:
        body = re.sub(rf'\b{copy}\b', counter, body)
    first, last = span
    before, after = source[first:loop.start()], source[end:last]
    after = re.sub(masked, counter, after)
    if copy:
        uses = len(re.findall(rf'\b{copy}\b', _blank(after)))
        safe = [m for m in re.finditer(rf'\b{copy}\s*(?:<|>=)\s*({NUM})', _blank(after)) if int(m[1], 0) < bound]
        if uses != len(safe) or re.search(rf'\b{copy}\b', _declaration_free(before, copy)):
            return None
        after = re.sub(rf'\b{copy}\b', counter, after)
    rest = _declaration_free(before + after, counter)
    # any other read of the word counter must have been through the mask
    if len(re.findall(rf'\b{counter}\b', _blank(rest))) > len(re.findall(rf'\b{counter}\s*(?:<|>=)\s*{NUM}', _blank(rest))):
        return None
    declared = _declaration(before, counter)
    if not declared:
        return None
    narrow = f'{MASKS[mask]} {counter};'
    lead = declared[0][:len(declared[0]) - len(declared[0].lstrip())]
    before = before[:declared.start()] + lead + narrow + before[declared.end():]
    if copy:
        gone = _declaration(before, copy)
        if gone:
            before = before[:gone.start()] + before[gone.end():]
    shape = f'for ({counter} = 0; {counter} < {bound}; {counter}++)\n    {{{body.rstrip()}\n    }}'
    return source[:first] + before + shape + after + source[last:]


def _declaration_free(text, name):
    found = _declaration(text, name)
    return text if not found else text[:found.start()] + text[found.end():]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    helpers = _helpers(clean)
    opening = clean.find('{', span[0])
    out = []
    for loop in WHILE.finditer(clean, opening, span[1]):
        child = _rewrite(source, clean, (opening, span[1]), loop, helpers)
        if child:
            out.append((FAMILY, child))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring
