"""A literal set before a branch that only the code on one side reads, set at the head of that side.

m2c writes `flag = 1;` in front of `if (c) { .. } else { total += flag; .. }` (or in front of a guard that leaves,
`if (c) { ..; goto out; } total += flag;`) because the target's `li` sits in the branch's delay slot. The delay slot
can also be filled from the head of the branch's target, which is where the source had the assignment. The two are not
the same program to the compiler: set in front of the branch, the constant is known on both sides, so the side that
never reads `flag` may compare against its register (`bne $v0,$a2` where the target loads `li $v0,1`). Set at the
head of the reading side it is known there alone.

On an SN GCC 2.8.1 N64 object-update routine (263 instructions) the target held 1 in `$a2` and used the register for
`+ 1` and `^ 1` (`addu $v1,$v1,$a2`, `xor $a2,$v0,$a2`) in the side that set it, while the other side loaded its own
`li $v0,1`. The assignment moved to the head of that side took the saved score from 2390 to 1880, which suggested a
loop around the whole branch had been needed to hide the constant; none was. That the register stands in for the
literal after reload (`reload_cse_regs`) is a hypothesis from the cse dump, which still adds the constant 1, not
confirmed in the compiler source.

Children (`constant_into_reading_arm`): each `V = K;` directly before an `if` whose condition does not read `V`, where
every other use of the local `V` is on one side: in one arm of the `if`/`else`, or, for a guard with no `else` that
ends in `return` or `goto`, after the guard in the same block.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, block_open, lines, mentions, relaid

FAMILY = 'constant_into_reading_arm'
FAMILIES = (FAMILY,)
LIMIT = 8
_SET = re.compile(r'(?P<v>[A-Za-z_]\w*) = -?(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?;')
_LEAVES = re.compile(r'(?:return\b[^;]*|goto (?P<label>[A-Za-z_]\w*));')


def _uses(body, name, skip):
    """The indexes of the lines that name `name`, other than its declaration and the line `skip`."""
    declared = re.compile(rf'(?:(?:unsigned|signed) )?[A-Za-z_]\w*[ \t]+{name};')
    return [i for i, line in enumerate(body)
            if i != skip and mentions(line.text, name) and not declared.fullmatch(line.stripped)]


def _local(body, name):
    declared = re.compile(rf'(?:(?:unsigned|signed) )?[A-Za-z_]\w*[ \t]+{name};')
    text = '\n'.join(line.text for line in body)
    return any(declared.fullmatch(line.stripped) for line in body) and not re.search(rf'&\s*{name}\b(?!\s*(?:\.|->|\[))', text)


def _block_limit(body, start):
    """The index of the line that closes the block holding the line `start` (the body's end for the outer block)."""
    depth = 0
    for i in range(start, len(body)):
        depth += body[i].text.count('{') - body[i].text.count('}')
        if depth < 0:
            return i
    return len(body)


def _moved(source, body, i, opening):
    """The source with the line `i` taken out and written as the first statement of the block opened at `opening`."""
    following = body[opening + 1]
    text = following.indent + body[i].stripped + '\n'
    return apply(source, [(body[i].start, body[i].end, ''), (following.start, following.start, text)])


def variants(source, name):
    source = relaid(source, name)
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body):
        hit = _SET.fullmatch(line.stripped)
        if not hit or i + 1 >= len(body) or not body[i + 1].stripped.startswith('if (') or not _local(body, hit['v']):
            continue
        # not the arm of an unbraced statement above
        if i and not body[i - 1].stripped.endswith((';', '{', '}', ':')):
            continue
        value = hit['v']
        test = i + 1
        opening = block_open(body, test)
        closing = block_end(body, opening) if opening is not None else None
        if closing is None or mentions(body[test].text, value):
            continue
        uses = _uses(body, value, i)
        if not uses:
            continue
        if closing + 1 < len(body) and body[closing + 1].stripped == 'else':
            other = block_open(body, closing + 1)
            end = block_end(body, other) if other is not None else None
            if end is None:
                continue
            for first, last in ((opening, closing), (other, end)):
                if all(first < use < last for use in uses) and first + 1 < last:
                    out.append((FAMILY, _moved(source, body, i, first)))
            continue
        if closing + 1 >= len(body) or body[closing + 1].stripped.startswith('else'):
            continue
        leaves = _LEAVES.fullmatch(body[closing - 1].stripped)
        limit = _block_limit(body, closing + 1)
        if not leaves or not all(closing < use < limit for use in uses):
            continue
        if leaves['label']:
            at = [j for j, other_line in enumerate(body) if other_line.stripped.startswith(leaves['label'] + ':')]
            # what runs from the label must not read the value the guard's path no longer sets
            if len(at) != 1 or any(use >= at[0] for use in uses):
                continue
        following = body[closing + 1]
        out.append((FAMILY, apply(source, [(line.start, line.end, ''),
                                           (following.start, following.start, following.indent + line.stripped + '\n')])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)
