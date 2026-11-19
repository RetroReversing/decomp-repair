"""Equal constant returns written once, the others jumping to it.

gcc 2.7.2 gives every `return 1;` its own copy of the constant load, scheduled where it falls; where the game's code
jumps from one path to the other path's return, the constant's register follows the shared tail instead. An N64
function returning 1 from two paths was 20 points off (the paths' stores took `$v1` where the game used `$v0`) and
exact once the first `return 1;` became `goto` to a label on the second. Each variant keeps one of the returns of a
repeated constant and points the others at it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_return'
FAMILIES = (FAMILY,)

RETURN = re.compile(r'\breturn\s+(-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    groups = {}
    for m in RETURN.finditer(clean, opening, end):
        groups.setdefault(int(m[1], 0), []).append(m)
    result = []
    for value, found in groups.items():
        if len(found) < 2 or len(found) > 4:
            continue
        label = f'__shared_return_{abs(value)}{"n" if value < 0 else ""}'
        if label in clean:
            continue
        for keep in (found[-1], found[0]):
            text = source
            for m in sorted(found, key=lambda m: m.start(), reverse=True):
                if m is keep:
                    text = text[:m.start()] + f'{label}:\n    ' + text[m.start():]
                else:
                    text = text[:m.start()] + f'goto {label};' + text[m.end():]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result
