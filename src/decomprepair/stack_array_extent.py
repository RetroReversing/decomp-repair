"""A stack array handed to a call, grown to the room the target's frame gives it.

m2c sizes an array it declares for the stack (`s32 sp18[2];`) by the elements the function itself reads back, but the
callee it is passed to may write more of it: a three-word vector filled by a transform (`out[0]`, `out[1]`, `out[2]`)
read for only its first two words. The array then ends short, every later stack object and saved register moves down,
and the frame is 8 bytes smaller than the target's. The target's own frame bounds it: the array runs up to the next
offset the target stores to or takes the address of. An N64 function (KMC GCC 2.7.2 `-O1 -g`, frame 0x30 against the
game's 0x38, `&sp28` at 0x20 against 0x28) was exact with `s32 sp18[3]` (7 -> 0); an unused padding array
(`frame_gap_scaffold`) also sized the frame, but the game's source had no such array.

Offered for each array whose name is passed to a call, from one element more up to the measured room (at most four
children, smallest first: the smallest that fits is usually what the callee writes).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .stack_extent_repairs import SIZES, stack_marks

FAMILY = 'stack_array_extent'
FAMILIES = (FAMILY,)

ARRAY = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*)\s+(?P<name>sp(?P<offset>[0-9A-Fa-f]+))'
                   r'\s*\[\s*(?P<count>0x[0-9A-Fa-f]+|\d+)\s*\]\s*;')


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    marks = stack_marks(asm)
    result = []
    for hit in ARRAY.finditer(clean, opening, end):
        var, offset, count = hit['name'], int(hit['offset'], 16), int(hit['count'], 0)
        size = SIZES.get(hit['type'])
        if size is None or count < 1:
            continue
        rest = clean[hit.end():end]
        # the array itself is an argument of a call: something else may write more of it than the function reads
        if not re.search(r'[(,]\s*' + var + r'\s*[,)]', rest):
            continue
        # the array's own element stores are inside it; the next object starts past what is declared
        later = [m for m in marks if m >= offset + count * size]
        if not later:
            continue
        room = later[0] - offset
        if room > 0x400 or room // size <= count:
            continue
        for wanted in range(count + 1, room // size + 1):
            text = source[:hit.start('count')] + str(wanted) + source[hit.end('count'):]
            result.append((FAMILY, text))
            if len(result) >= 4:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm')}
