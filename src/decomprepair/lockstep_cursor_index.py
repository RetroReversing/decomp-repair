"""Cursors that step with a counter through tables, written as the counter's index: `*bb`, `*cc`, `k++` -> `T[k]`.

A table-building loop reads several parallel tables at the same position and steps through them together:

    u32 *bb = D_800B3134 + k;
    u32 *cc = D_800B2CB8 + k;
    do {
        ... *bb ... *cc ...
        bb++;
        cc++;
        k++;
    } while (...);

where `k` carries on from an earlier loop (`table_cursor_index` starts the counter at 0 and reads m2c's byte steps).
GCC 2.7.2's loop pass makes its own induction variables of `T[k]`: one biv `k` and one derived giv per table, each
stepped where loop.c puts the step, with the inner loops' copies of them hoisted. A cursor of its own is a biv beside
it: another register, its step where the source wrote it, and no copy for the inner loop. Written as the index, the loop
is the one the game had and the compiler's own reduction gives the target's registers and its `lui`/`addu` set-up
(a 681-instruction bit-stream decoder, KMC gcc 2.7.2: the table loops went 11271 -> 6927 from this step alone;
docs/learnings/function/bit-stream-decoder-table-loops-and-register-roles.md).

Offered when, in a loop body, a pointer local is stepped once by a statement of the body itself (not under a branch),
the counter named in its start is stepped once likewise, the pointer is started as `BASE + k` or `&BASE[k]` in the
block before the loop with neither assigned between, and the pointer's only other uses are `*p` reads and writes that
sit before both steps or after both (a read between them sees the two a step apart). Every cursor of the loop that
qualifies is rewritten in one child (they pay off together), and, for a loop with several, each alone.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .invariant_shift_local import _assigned, _loops

FAMILY = 'cursor_counter_index'
FAMILIES = (FAMILY,)


def _depths(text):
    depth, out = 0, []
    for char in text:
        if char in '{([':
            depth += 1
        out.append(depth)
        if char in '})]':
            depth -= 1
    return out


def _statement_start(clean, at, floor):
    """The start of the statement that ends at `at` (just after the previous `;`, `{` or `}`)."""
    pos = at
    while pos > floor and clean[pos - 1] not in ';{}':
        pos -= 1
    return pos


def _steps(clean, begin, end, name):
    """The loop body's own steps of `name` (brace depth 0 in the body): `name++;`, `++name;`, `name += E;`, as
    (start, end, amount) with amount '1' for an increment and E's text, whitespace removed, for `+=`."""
    depths = _depths(clean[begin:end])
    found = []
    for hit in re.finditer(rf'(?<![\w+])(?:{name}\s*\+\+|\+\+\s*{name})\s*;', clean[begin:end]):
        if depths[hit.start()] == 0:
            found.append((begin + hit.start(), begin + hit.end(), '1'))
    for hit in re.finditer(rf'(?<![\w+])\b{name}\s*\+=\s*(?P<e>[^;{{}}]+?)\s*;', clean[begin:end]):
        if depths[hit.start()] == 0:
            found.append((begin + hit.start(), begin + hit.end(), re.sub(r'\s+', '', hit['e'])))
    return found


def _writes(text, name):
    """Every place the loop text assigns, steps or takes the address of `name`."""
    return re.findall(rf'(?<![\w+*])(?:{name}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{name}\b)'
                      rf'|(?<![&\w])&\s*{name}\b', text)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pointers = set(re.findall(rf'\*\s*({IDENT})\s*(?=[;=,])', clean[part.opening:part.end]))
    out = []
    for start, opening, closing, stop in _loops(clean, part.opening + 1, part.end):
        body = (opening + 1, closing)
        candidates = []
        for pointer in sorted(pointers):
            steps = _steps(clean, *body, pointer)
            if len(steps) != 1 or len(_writes(clean[start:stop], pointer)) != 1:
                continue
            block = _block_start(clean, start, part.opening)
            if block is None:
                continue
            init = None
            for hit in re.finditer(rf'(?:\b[\w ]+\*\s*)?\b{pointer}\s*=\s*(?:(?P<base>{IDENT})\s*\+\s*(?P<k1>{IDENT})'
                                   rf'|&\s*(?P<base2>{IDENT})\s*\[\s*(?P<k2>{IDENT})\s*\])\s*;', clean[block:start]):
                init = hit
            if init:
                base, counter = (init['base'], init['k1']) if init['base'] else (init['base2'], init['k2'])
            else:
                init, counter = _zero_start(clean, block, start, body, pointer)
                if not init:
                    continue
                base = init['base']
            ksteps = _steps(clean, *body, counter)
            if len(ksteps) != 1 or ksteps[0][2] != steps[0][2] or _assigned(clean[block + init.end():start], counter) \
                    or re.search(rf'\b{pointer}\b', clean[block + init.end():start]):
                continue
            if len(_writes(clean[start:stop], counter)) != 1:
                continue
            after = sorted(step[1] for step in (steps[0], ksteps[0]))[1]
            before = sorted(step[0] for step in (steps[0], ksteps[0]))[0]
            uses = []
            ok = True
            reach = _block_end(clean, block, part.end)
            later = False
            for hit in re.finditer(rf'\b{pointer}\b', clean[part.opening:part.end]):
                at = part.opening + hit.start()
                if at < block:
                    continue  # an earlier, independent use of the name
                if at >= reach:
                    if not later and not re.match(rf'\b{pointer}\s*=(?!=)', clean[at:]):
                        ok = False  # read again after the loop before it is started over
                        break
                    later = True
                    continue
                if block + init.start() <= at < block + init.end() or steps[0][0] <= at < steps[0][1]:
                    continue
                line = clean.rfind('\n', 0, at) + 1
                if re.match(rf'[ \t]*(?:\w+\s+)+\*\s*{pointer}\s*;', clean[line:]) and at < start:
                    continue  # the block's own declaration of the pointer
                if not (start <= at < stop) or not re.match(rf'\b{pointer}\b', clean[at:]):
                    ok = False
                    break
                lead = clean[:at].rstrip()
                if not lead.endswith('*') or re.search(r'[\w)\]]\s*\*$', lead[:-1].rstrip() + '*') and \
                        re.search(r'[\w)\]]$', lead[:-1].rstrip()):
                    ok = False  # a product `x * p`, or not a dereference at all
                    break
                if clean[at + len(pointer):].lstrip().startswith(('++', '--', '[')):
                    ok = False
                    break
                if before < at < after and not (at < before or at >= after):
                    ok = False  # between the two steps
                    break
                uses.append((lead.rindex('*'), at + len(pointer)))
            if not ok or not uses:
                continue
            edits = []
            for first, last in uses:
                edits.append((first, last, f'{base}[{counter}]'))
            initial = _statement_start(clean, block + init.start(), block)
            edits.append((initial if clean[initial:block + init.start()].strip() == '' else block + init.start(),
                          block + init.end(), ''))
            edits.append((_statement_start(clean, steps[0][0], opening), steps[0][1], ''))
            declaration = re.search(rf'(?m)^[ \t]*(?:\w+\s+)+\*\s*{pointer}\s*;[ \t]*\n', clean[part.opening:part.end])
            mentions = len(re.findall(rf'\b{pointer}\b', clean[part.opening:part.end]))
            if declaration and mentions == 3 + len(uses):
                edits.append((part.opening + declaration.start(), part.opening + declaration.end(), ''))
            elif declaration and not re.search(rf'\b{pointer}\b', clean[part.opening + declaration.end():part.end]
                                             .replace(clean[part.opening + declaration.start():part.opening + declaration.end()], '')):
                edits.append((part.opening + declaration.start(), part.opening + declaration.end(), ''))
            candidates.append((pointer, edits))
        if not candidates:
            continue
        everything = [e for _, edits in candidates for e in edits]
        out.append((FAMILY, edit(source, _unique(everything))))
        if len(candidates) > 1:
            for _, edits in candidates:
                out.append((FAMILY, edit(source, _unique(edits))))
    return out


def _zero_start(clean, block, start, body, pointer):
    """`p = BASE;` before the loop beside a counter set to 0 there: (the init's match, the counter) or (None, None).

    The loop's other once-stepped local whose last assignment before the loop, in the same block, is `k = 0;` is the
    counter `p` keeps pace with, so `*p` is `BASE[k]` (a byte table's walk in a code-table builder: `bp = T; tp = tab;
    i = 0; do { .. *bp .. *tp = ..; bp++; i++; tp++; } while ((i >> tb) == 0);`, 410 -> 350 with both written as the
    index, 681-instruction bit-stream decoder, KMC GCC 2.7.2)."""
    init = None
    for hit in re.finditer(rf'(?:\b[\w ]+\*\s*)?\b{pointer}\s*=\s*(?P<base>{IDENT})\s*;', clean[block:start]):
        init = hit
    if not init:
        return None, None
    steps = _steps(clean, *body, pointer)
    for zero in re.finditer(rf'(?<![\w.>])({IDENT})\s*=\s*0\s*;', clean[block:start]):
        counter = zero.group(1)
        if counter == pointer:
            continue
        ksteps = _steps(clean, *body, counter)
        if len(ksteps) != 1 or ksteps[0][2] != steps[0][2]:
            continue
        if _assigned(clean[block + zero.end():start], counter):
            continue
        return init, counter
    return None, None


def _unique(edits):
    seen, kept = set(), []
    for item in edits:
        if (item[0], item[1]) not in seen:
            seen.add((item[0], item[1]))
            kept.append(item)
    return kept


def _block_end(clean, block, ceiling):
    """The position just past the `}` that closes the block whose body starts at `block`."""
    depth = 0
    for pos in range(block, ceiling):
        if clean[pos] == '{':
            depth += 1
        elif clean[pos] == '}':
            if depth == 0:
                return pos + 1
            depth -= 1
    return ceiling


def _block_start(clean, at, floor):
    """The `{` that opens the block holding `at`, plus one."""
    depth = 0
    for pos in range(at - 1, floor - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos + 1
            depth -= 1
    return None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
