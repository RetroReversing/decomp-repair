"""Empty `case`s that make a sparse `switch` dense enough for the jump table the target has.

GCC 2.x builds a jump table only when the range of the labels is at most ten times their number; otherwise it builds a
tree of compares. It counts one for a run of consecutive values that share an arm, and two when the run is longer than
one value. The game's source named values its switch did nothing for (unused kinds of an enum), which leave no code
behind: the table holds the default's address for them, the same as for any other missing value. A draft written from
the table has only the values with code, so it can fall short of the ratio and compile to a tree.

The target says what the table spans (`addiu $v1, $v0, -LOW; sltiu $v0, $v1, COUNT` and a `jr`). The child names the
span's two ends and enough unused values inside it, holes between the cases first, for the ratio to hold. They share
the default's arm, or an arm of their own that only `break`s at the end of the switch, so the program does the same.

An SN GCC 2.8.1 N64 dispatch loop (337 instructions, `-O2 -fno-strength-reduce`): 99 labels with code over 1..1048 and a
table of 1049 entries (1..1049). They counted 93, so the draft compiled to 70 `beq`s; a dozen empty labels
(holes in its series, and 1049) give the target's table. Which values the game named cannot be read back from the target.
"""
import re

from .integer_repair_support import view
from .switch_empty_case import _CASE, _OTHER_CASE, _switches
from .switch_range_repairs import ranges

FAMILY = 'switch_table_density'
FAMILIES = (FAMILY,)
RATIO = 10  # GCC 2.x: a tree when the range is more than this many times the count
MAX_ADDED = 64
MAX_SPAN = 8192
_LABEL = re.compile(r'(?<![\w])(?:case\s+(-?(?:0[xX][0-9A-Fa-f]+|\d+))|default)\s*:')
_JUMP = re.compile(r'\bjr\s+\$(?!ra\b|31\b)\w+')
_CHECK = re.compile(r'\bsltiu\b')


def tables(asm):
    """(lowest value, entry count) of each range check that a jump through a register follows."""
    lines = (asm or '').splitlines()
    out = []
    for number, line in enumerate(lines):
        if _CHECK.search(line) and any(_JUMP.search(later) for later in lines[number + 1:number + 9]):
            # `ranges` reads the bias from the lines before the check
            found = ranges('\n'.join(lines[max(0, number - 4):number + 1]))
            out.extend(item for item in found[:1] if item not in out)
    return out


def arms(body):
    """{value: arm number} of a switch body's labels, and the default's arm number (or None). Labels with only white
    space between them head one arm."""
    values, default, arm, end = {}, None, 0, None
    for label in _LABEL.finditer(body):
        if end is None or body[end:label.start()].strip():
            arm += 1
        end = label.end()
        if label[1] is None:
            default = arm
        else:
            values[int(label[1], 0)] = arm
    return values, default


def count(values):
    """What GCC 2.x counts: each run of consecutive values in one arm is one, or two when it is longer than one."""
    total, run, previous = 0, 0, None
    for value in sorted(values):
        joined = previous is not None and value == previous + 1 and values[value] == values[previous]
        run = run + 1 if joined else 1
        if run <= 2:
            total += 1
        previous = value
    return total


def padding(values, arm, low, size):
    """The values to add (each into `arm`) so that the switch spans the table and is dense enough; None when it
    already is, cannot be this table's, or would take too many."""
    high = low + size - 1
    if not values or size > MAX_SPAN or min(values) < low or max(values) > high:
        return None
    have = dict(values)
    if min(have) == low and max(have) == high and high - low <= RATIO * count(have):
        return None
    added = []

    def add(value):
        before = count(have)
        have[value] = arm
        if count(have) > before or value in (low, high):
            added.append(value)
        else:
            del have[value]

    for end in (low, high):
        if end not in have:
            add(end)
    used = sorted(values)
    # the holes in a series first (the unused members of an enum), then one past each series, then every other value
    holes = [v for a, b in zip(used, used[1:]) if b - a <= 4 for v in range(a + 1, b)]
    after = [a + 1 for a, b in zip(used, used[1:]) if b - a > 4]
    spread = range(low, high + 1, 2)
    for pool in (holes, after, spread):
        for value in pool:
            if high - low <= RATIO * count(have):
                break
            if value not in have:
                add(value)
    if high - low > RATIO * count(have) or not added or len(added) > MAX_ADDED:
        return None
    return sorted(added)


def variants(source, name, asm):
    checks = tables(asm)
    part = view(source, name) if checks else None
    if not part:
        return []
    out = []
    for brace, end, body in _switches(part):
        if len(_CASE.findall(body)) != len(_OTHER_CASE.findall(body)):
            continue
        values, default = arms(body)
        if len(values) < 4:
            continue
        hexed = '0x' in ''.join(_CASE.findall(body)).lower()
        for low, size in checks:
            arm = default if default is not None else -1
            added = padding(values, arm, low, size)
            if not added:
                continue
            labels = [f'case {hex(v) if hexed and not -10 < v < 10 else v}:' for v in added]
            if default is not None:
                at = brace + re.search(r'(?<![\w])default\s*:', body).start()
                text = ' '.join(labels) + ' '
            else:
                at = end
                before = body.rstrip()
                left = '' if re.search(r'(?:\bbreak|\bcontinue|\breturn\b[^;{}]*|\bgoto\s+\w+)\s*;$', before) else 'break; '
                text = left + ' '.join(labels) + ' break; '
            child = (FAMILY, source[:at] + text + source[at:])
            if child not in out:
                out.append(child)
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 1500}
