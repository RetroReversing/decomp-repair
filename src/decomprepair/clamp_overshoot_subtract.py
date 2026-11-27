"""A length clipped to a far edge, written as taking the overshoot off it.

    if (y + h > bottom) {               if (y + h > bottom) {
        h = bottom - y;          ->         h -= y + h - bottom;
    }                                   }

Both fold to the same `bottom - y`, so the instructions do not change, but the second spelling names `h` once more before
the fold. That is one more reference for the allocator, which moved a whole set of registers: two N64 sprite drawers
(KMC GCC 2.7.2 `-O1`, 803 and 843 instructions) stood at 85 with only register rows, through some two thousand other
spellings, and were both exact with the bottom edge written this way (one child from the 85; both edges at once scored 55).

Children (`clamp_overshoot_subtract`): each `L = M - P;` that is the first statement under an `if` comparing `P + L`
with `M` (either order, either operand order), rewritten as `L -= P + L - M;`, all at once and then one at a time.
"""
import re

from .csource import _blank, find

FAMILY = 'clamp_overshoot_subtract'
FAMILIES = (FAMILY,)
LIMIT = 8
TERM = r'[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*'
CLAMP = re.compile(rf'(?<![\w.>])if \((?P<test>[^;{{}}]*?)\)\s*\{{?\s*(?P<set>(?P<l>{TERM}) = (?P<m>{TERM}) - (?P<p>{TERM});)')


def _tests(length, limit, start):
    """The ways of writing `start + length` is past `limit`."""
    sums = (f'{start} + {length}', f'{length} + {start}')
    return {text for total in sums for op, flipped in (('>', '<'), ('>=', '<='))
            for text in (f'{total} {op} {limit}', f'{limit} {flipped} {total}')}


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    sites = []
    for found in CLAMP.finditer(clean, span[0], span[1]):
        length, limit, start = found['l'], found['m'], found['p']
        test = re.sub(r'\((?:unsigned |signed )?(?:char|short|int|long|[su](?:8|16|32))\)', '', found['test'])
        if len({length, limit, start}) == 3 and ' '.join(test.split()) in _tests(length, limit, start):
            sites.append((found.start('set'), found.end('set'), f'{length} -= {start} + {length} - {limit};'))
    sites = sites[:LIMIT]

    def write(chosen):
        text = source
        for begin, end, new in reversed(chosen):
            text = text[:begin] + new + text[end:]
        return FAMILY, text

    if not sites:
        return []
    result = [write(sites)]
    if len(sites) > 1:
        result += [write([site]) for site in sites]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
