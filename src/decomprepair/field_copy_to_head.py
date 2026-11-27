"""One field copied from another record, written first in its run of stores.

A function that fills a new record loads the field it takes from its parent into a register at the head of the block
and stores it where the scheduler finds room, many stores later, so m2c writes the copy where the store is. A load
written down there is issued down there: `lw v1, 0x34(parent)` at the head of the target's block, `lw v0` just before
the store in the draft's. `statement_slide` moves a statement at most four places, and `field_copy_group` gathers
every copy together, while the game's source had this one copy first and the others after the constants. A
112-instruction N64 object update (SN GCC 2.8.1 `-G0 -mips3 -O2`, 595) went to 390 from this move alone, nine
statements up, one of the four edits of its match.

A child moves `M2C_FIELD(q, T *, off) = M2C_FIELD(p, U *, off);` (the same offset of another record, casts allowed)
to the highest place of its run of simple statements it can reach while commuting with every statement it passes
(`statement_slide.commutes`: no call, no overlapping cell, no shared local written), and only when that is more than
`statement_slide`'s reach above. The head is not always the place: a game's constructor copied `x`, `y`, `z` and then
the angle from its parent before a run of constants, where m2c had written the angle copy last, eight statements down
(`lw` right after the third `lhu`, its `sw` at the end). The head scored worse; after the first copy it was one of the
five edits of the match (SN N64 GCC `-O2`, 101 instructions, 695). So after the heads a child also moves each such copy
to every place between the head and that reach. That the two records are different objects is an assumption; the judge
decides. One match each, not read in the compiler source."""
from .integer_repair_support import view
from .statement_slide import FIELD, REACH, _cells, _runs, commutes

FAMILY = 'field_copy_to_head'
FAMILIES = (FAMILY,)
LIMIT = 8
BELOW_LIMIT = 12  # places between the head and statement_slide's reach


def _is_copy(text):
    left, equals, right = _cells(text).rstrip('; \t\n').partition('=')
    to = FIELD.fullmatch(left.strip())
    came = list(FIELD.finditer(right))
    if not equals or not to or len(came) != 1 or came[0].end() != len(right.rstrip()):
        return False
    casts = right[:came[0].start()]
    return (casts.replace('(', '').replace(')', '').strip() in ('', 's8', 'u8', 's16', 'u16', 's32', 'u32', 'f32')
            and came[0]['base'] != to['base'] and int(came[0]['off'], 0) == int(to['off'], 0))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    heads, below = [], []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end)):
        for index, (start, end) in enumerate(run):
            text = part.clean[start:end]
            if index <= REACH or not _is_copy(text):
                continue
            top = index
            while top and commutes(part.clean[run[top - 1][0]:run[top - 1][1]], text):
                top -= 1
            if index - top <= REACH:
                continue
            heads.append(_moved(source, run[top][0], start, end))
            below += [_moved(source, run[place][0], start, end) for place in range(top + 1, index - REACH)]
    return [(FAMILY, child) for child in heads[:LIMIT] + below[:BELOW_LIMIT]]


def _moved(source, first, start, end):
    """`source` with the statement `start:end` written before the one at `first`."""
    indent = source[source.rfind('\n', 0, first) + 1:first]
    gap = '\n' + indent if not indent.strip() else ' '
    line = source.rfind('\n', 0, start) + 1
    cut = line if not source[line:start].strip() and source[end:end + 1] == '\n' else start
    stop = end + 1 if cut == line and cut != start else end
    return source[:first] + source[start:end] + gap + source[first:cut] + source[stop:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
