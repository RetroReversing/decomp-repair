"""A guard flag m2c reused as the loop counter under it, given the counter of a sibling loop; and the address locals
set before each loop written once before the loop around them.

Matched on a 1928-instruction collision sweep (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) that stood at 2798. m2c
named one register's values one variable, so a flag that guards a triangle walk was also the walk's counter:

    if (flag < n) { flag = 0; p = &point; do { .. flag & 0xFFFF .. flag += 1; } while ((flag & 0xFFFF) < n); }

The target compares the flag (`sltu $v0, $s1, $v0`, the flag known zero there) and counts in another register, the one
the next walk counts in (`move $s4, $zero` in both walks). One pseudo for flag and counter lives across both and takes
a saved register the target spends elsewhere. Written with the sibling walk's counter, the flag dies at the guard.

That alone was neutral (2798 -> 2773): the register it frees went to the next pseudo in global.c's priority order. The
target keeps two segment addresses (`&point`, `&other`) in saved registers set once before the object loop, where
m2c gave each walk its own copy (`p = &point;` before the walk, `p2 = &point;` before another one); written once, each
alone was worse (5551: the address ranked just below a counter that kept its register). Together: 2798 -> 1484, and the
frame, 0x10 short, came right (the walks' other addresses and the hit index spilled as in the target).

flag_counter_split
    `if (v < n) { v = 0; .. do { ..v.. } while (..v..); }` with `v` read after the loop only once it is assigned again:
    the `v = 0;` and the loop written with `c`, a counter another loop of the function zeroes and steps (an integer
    local the loop does not mention). Children for up to three such counters, nearest after the loop first, each also
    with the zero moved above the guard (reorg fills the guard's delay slot from above the branch).
flag_counter_split_hoist
    The same, with every address local `p = &x;` assigned only directly above a `do` (several names for one address
    merged into the first) assigned once above the innermost `do` that holds them all.

Hypothesis from the match, not from the compiler source: the split shortens the flag's life to the guard, and an
address local assigned once outside the loop has one long life whose references outrank the walks' other values.
The exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'flag_counter_split'
FAMILY_HOIST = 'flag_counter_split_hoist'
FAMILIES = (FAMILY, FAMILY_HOIST)
LIMIT = 12
COUNTERS = 3

_GUARD = re.compile(rf'\bif\s*\(\s*({IDENT})\s*<')
_INT = r'(?:register\s+)?(?:u8|s8|u16|s16|u32|s32|int|short|long|unsigned(?:\s+(?:int|short|long))?|signed(?:\s+int)?)'
_DO = re.compile(r'\bdo\b\s*{')


def _word(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _loop_end(clean, start, stop):
    """The end of the `do { } while (..);` statement that starts at `start`, or None."""
    brace = clean.index('{', start)
    body_end = close(clean, brace, '{', '}')
    if not body_end:
        return None
    tail = re.match(r'\s*while\s*\(', clean[body_end:stop])
    if not tail:
        return None
    test_end = close(clean, body_end + tail.end() - 1)
    semi = re.match(r'\s*;', clean[test_end:stop]) if test_end else None
    return test_end + semi.end() if semi else None


def _declared_int(clean, name):
    return re.search(rf'(?m)^\s*{_INT}\s+{re.escape(name)}\s*;', clean)


def _counters(clean, opening, end, region, flag):
    """Integer locals another loop of the function zeroes and steps, nearest after the region first."""
    found = {}
    for loop in _DO.finditer(clean, opening, end):
        if region[0] <= loop.start() < region[1]:
            continue
        stop = _loop_end(clean, loop.start(), end)
        if not stop or (loop.start() < region[0] and stop >= region[1]):
            continue
        text = clean[loop.start():stop]
        for step in re.finditer(rf'(?:\+\+\s*({IDENT})|({IDENT})\s*(?:\+\+|\+=\s*1\b))', text):
            name = step[1] or step[2]
            if name == flag or not _declared_int(clean, name):
                continue
            if _word(name).search(clean, region[0], region[1]):
                continue
            if not re.search(rf'(?<![\w.>]){re.escape(name)}\s*=\s*0\s*;', clean[opening:end]):
                continue
            distance = loop.start() - region[1] if loop.start() >= region[1] else end + region[0] - loop.start()
            found[name] = min(distance, found.get(name, distance))
    return [name for name, _ in sorted(found.items(), key=lambda item: (item[1], item[0]))[:COUNTERS]]


def _read_later(clean, after, end, name):
    """The next mention of `name` after the region is a read (not an assignment)."""
    hit = _word(name).search(clean, after, end)
    if not hit:
        return False
    return not re.match(r'\s*=(?!=)', clean[hit.end():end])


def _splits(part):
    clean, source = part.clean, part.source
    out = []
    for guard in _GUARD.finditer(clean, part.opening, part.end):
        flag = guard[1]
        cond_end = close(clean, guard.start() + guard.group(0).index('('))
        if not cond_end:
            continue
        brace = re.match(r'\s*{', clean[cond_end:part.end])
        if not brace:
            continue
        inside = cond_end + brace.end()
        zero = re.match(rf'\s*{re.escape(flag)}\s*=\s*0\s*;', clean[inside:part.end])
        if not zero:
            continue
        loop = _DO.search(clean, inside + zero.end(), part.end)
        if not loop or _word(flag).search(clean, inside + zero.end(), loop.start()):
            continue
        stop = _loop_end(clean, loop.start(), part.end)
        if not stop or not _word(flag).search(clean, loop.start(), stop) or _read_later(clean, stop, part.end, flag):
            continue
        zero_start = inside + zero.start() + len(zero[0]) - len(zero[0].lstrip())
        region = (zero_start, stop)
        line = source.rfind('\n', 0, guard.start()) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        for counter in _counters(clean, part.opening, part.end, region, flag):
            text = _word(flag).sub(counter, source[region[0]:region[1]])
            plain = source[:region[0]] + text + source[region[1]:]
            out.append(plain)
            init = re.match(rf'{re.escape(counter)}\s*=\s*0\s*;[ \t]*\n', text)
            if init:
                zero_line = source.rfind('\n', 0, region[0]) + 1
                head = source[:line] + indent + counter + ' = 0;\n' + source[line:zero_line]
                out.append(head + text[init.end():] + source[region[1]:])
    return out


def _address_hoist(source, name):
    """Address locals assigned only directly above a `do`, merged per address and assigned once above the loop that
    holds every such assignment."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    sets = {}
    for found in re.finditer(rf'(?m)^[ \t]*({IDENT})\s*=\s*(&\s*[^;=]+?)\s*;[ \t]*\n', clean[:part.end]):
        if found.start() < part.opening:
            continue
        after = re.match(r'(?:\s*\n)*\s*', clean[found.end():part.end])
        if not _DO.match(clean, found.end() + after.end()):
            continue
        sets.setdefault(found[1], []).append(found)
    groups = {}
    for local, hits in sets.items():
        total = len(re.findall(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', clean[part.opening:part.end]))
        if len(hits) != 1 or total != 1:
            continue
        address = re.sub(r'\s+', '', hits[0][2])
        if not re.fullmatch(rf'&{IDENT}(?:\[\d+\])?', address):
            continue
        groups.setdefault(address, []).append((local, hits[0]))
    groups = {a: g for a, g in groups.items() if len(g) > 1}
    if not groups:
        return None
    every = [hit for group in groups.values() for _, hit in group]
    first, last = min(h.start() for h in every), max(h.end() for h in every)
    outer = None
    for loop in _DO.finditer(clean, part.opening, first):
        stop = _loop_end(clean, loop.start(), part.end)
        if stop and stop >= last:
            outer = loop
    if not outer:
        return None
    text = source
    edits = []
    for address, group in groups.items():
        keep = group[0][0]
        for _, hit in group:
            edits.append((hit.start(), hit.end(), ''))
        removed = [(hit.start(), hit.end()) for _, hit in group]
        for local, _ in group[1:]:
            for use in _word(local).finditer(clean, 0, part.end):
                if any(a <= use.start() < b for a, b in removed):
                    continue
                if not re.match(rf'(?m)^\s*(?:{IDENT}\s*)+\*\s*$', clean[clean.rfind('\n', 0, use.start()) + 1:use.start()]):
                    edits.append((use.start(), use.end(), keep))
                else:
                    line_end = clean.index('\n', use.end())
                    edits.append((clean.rfind('\n', 0, use.start()) + 1, line_end + 1, ''))
    line = source.rfind('\n', 0, outer.start()) + 1
    indent = re.match(r'[ \t]*', source[line:])[0]
    lines = ''.join(f'{indent}{group[0][0]} = {group[0][1][2].strip()};\n' for group in groups.values())
    edits.append((line, line, lines))
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + new + text[end:]
    return text


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    out = []
    for child in _splits(part):
        out.append((FAMILY, child))
        hoisted = _address_hoist(child, name)
        if hoisted and hoisted != child:
            out.append((FAMILY_HOIST, hoisted))
    seen, result = set(), []
    for family, text in out:
        if text != source and text not in seen:
            seen.add(text)
            result.append((family, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
