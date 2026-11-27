"""The unused wide local a search left behind, taken out.

`phantom_wide_local` adds `{ long long phantom_wide = x; }` to shift allocation ties, and the search keeps the block
when the score drops. A block the function does not need can cost more than it gains once the real source is
closer: on a 131-instruction spawn-point routine (SN GCC 2.8.1 `-O2 -mfp64`) it made the frame 8 bytes larger than the
target's (`addiu $sp, -0x28` for `-0x20`), eight of the differing rows. Nothing offered the way back, so the
scaffolding stayed in the saved best.

phantom_wide_drop
    Every `{ long long phantom_wide... = x; }` block removed at once, then each alone when there are several.
"""
import re

from .csource import _blank, find

FAMILY = 'phantom_wide_drop'
FAMILIES = (FAMILY,)

BLOCK = re.compile(r'\{\s*(?:(?:unsigned|signed)\s+)?(?:long\s+long|s64|u64)\s+phantom_\w+\s*=\s*[^;{}]*;\s*\}')


def _without(source, spans):
    for first, last in sorted(spans, reverse=True):
        line = source.rfind('\n', 0, first) + 1
        end = source.find('\n', last)
        end = len(source) if end < 0 else end
        if not source[line:first].strip() and not source[last:end].strip():
            first, last = line, min(end + 1, len(source))
        else:
            while last < len(source) and source[last] in ' \t':
                last += 1
        source = source[:first] + source[last:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    spans = [(m.start(), m.end()) for m in BLOCK.finditer(clean, span[0], span[1])]
    if not spans:
        return []
    result = [(FAMILY, _without(source, spans))]
    if len(spans) > 1:
        result += [(FAMILY, _without(source, [one])) for one in spans]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
