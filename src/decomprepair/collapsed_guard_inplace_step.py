"""A derived copy advanced in place and moved into the arm that uses it, after an identical-arm guard is collapsed.

m2c steps a value into a fresh local, `next = cur + 1;`, and then clamps and uses `next` in one arm of an `if`, while a
dead `if (next) { S } else { S }` (equal arms, so the condition decides nothing) keeps the copy live on the other path.
The game stepped the value itself, `cur += 1;`, inside the arm. Each edit alone is worse on a KMC
`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2` menu-update function (collapsing the guard 870 -> 880, stepping in place at
the old position 870 -> 1071 and 710 with the guard gone, sunk into the arm 590), and the in-place step is only
sound once the guard no longer reads the copy, so one child carries all three edits: the guard collapsed
(`identical_arm_collapse`), `cur` stepped at the head of the arm that uses the copy, and the copy renamed to `cur`
there. The step is made only when `cur` is not read inside that arm or after it, the copy is not read after the arm (earlier
reads of the same name are an older value and stay: m2c reuses a name for unrelated values), the arm is an `if` body,
and the statement is not in a loop (a `do { } while (0);` scope is not one). Offered alone as `derived_copy_in_place`
too, for sources with no guard to collapse. A candidate for the exact judge, never a verdict."""
import re

from . import identical_arm_collapse_repairs
from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

COMBINED = 'collapsed_guard_inplace_step'
ALONE = 'derived_copy_in_place'
FAMILIES = (COMBINED, ALONE)
LIMIT = 4
STEP = re.compile(rf'(?<![\w.])(?P<t>{IDENT})\s*=\s*(?P<v>{IDENT})\s*(?P<op>[+-])\s*(?P<c>{NUMBER})\s*;')


def _enclosing(clean, at, floor):
    """(start of `{`, end past `}`) of the innermost block around `at`, or None."""
    depth = 0
    for pos in range(at - 1, floor - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                end = close(clean, pos, '{', '}')
                return (pos, end) if end and end > at else None
            depth -= 1
    return None


def _in_loop(clean, at, floor):
    block = _enclosing(clean, at, floor)
    while block:
        head = clean[max(floor, block[0] - 80):block[0]]
        if re.search(r'\b(?:for|while)\s*\([^{};]*\)\s*$', head):
            return True
        if re.search(r'\bdo\s*$', head) and not re.match(r'\s*while\s*\(\s*0\s*\)', clean[block[1]:block[1] + 40]):
            return True  # (`do { } while (0);` is a scope, not a loop)
        block = _enclosing(clean, block[0], floor)
    return False


def _step(source, part, m):
    t, v = m['t'], m['v']
    if t == v:
        return None
    after = part.clean[m.end():part.end]
    first = re.search(rf'\b{t}\b', after)
    if not first:
        return None
    if _in_loop(part.clean, m.start(), part.opening):
        return None  # (earlier reads of the copy are an older value: m2c reuses a name, and they stay as they are)
    arm = _enclosing(part.clean, m.end() + first.start(), m.end())
    if not arm:
        return None
    head = part.clean[m.end():arm[0]]
    if not re.search(r'\bif\s*\([^{};]*\)\s*$', head):
        return None
    inside = part.clean[arm[0] + 1:arm[1] - 1]
    later = part.clean[arm[1]:part.end]
    if re.search(rf'\b{v}\b', inside) or re.search(rf'\b(?:{v}|{t})\b', later):
        return None
    if re.search(rf'\b{t}\b', part.clean[m.end():arm[0]]):
        return None
    new_inside = re.sub(rf'\b{t}\b', v, source[arm[0] + 1:arm[1] - 1])
    step = f'{v} = {v} {m["op"]} {m["c"]};'
    return [(m.start(), m.end(), ''), (arm[0] + 1, arm[1] - 1, f'\n      {step}' + new_inside)]


def _inplace(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for m in STEP.finditer(part.clean, part.opening, part.end):
        edits = _step(source, part, m)
        if edits:
            out.append(edit(source, edits))
    return out


def variants(source, name, header=''):
    out = []
    for _, collapsed in identical_arm_collapse_repairs.variants(source, name, header)[:LIMIT]:
        out.extend((COMBINED, text) for text in _inplace(collapsed, name)[:2])
    out.extend((ALONE, text) for text in _inplace(source, name)[:2])
    seen, result = set(), []
    for family, text in out:
        if text != source and text not in seen:
            seen.add(text)
            result.append((family, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 70}
