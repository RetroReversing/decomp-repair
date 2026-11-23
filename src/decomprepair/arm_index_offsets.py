"""A switch's arms that each read a different slot of one table, written back with the switch's index in the address.

A loop body that handles slot `j` of two tables in its own arm (`case 0:` the first label and the first buffer,
`case 1:` the second of each ...) was written once for every slot, with the index in the address:

    case 0: use(*(void **)((char *)ent + 0x418), (char *)ent + 0x438);
    case 1: use(*(void **)((char *)ent + 0x41C), (char *)ent + 0x448);
    case 2: use(*(void **)((char *)ent + 0x420), (char *)ent + 0x458);

where m2c (and every draft after it) writes each arm's constant offset. In the arm the compiler knows `j`, so the two
spellings are the same number, but not the same RTL: `ent + 0x418 + j * 4` gives the arm its own address pseudo, which
loop.c moves out of the loop (one hoisted register or spill slot per address, the target's six), where the constant
offset folds into the load and nothing is hoisted. In a 534-instruction panel builder the six hoisted addresses and the
spill slots they took were all there was to the frame difference, and the preheader's insns appeared only once the
arms spelled the index: 18163 -> 16151 and the arms' constants stopped being hoisted out of the loop with them
(the loop pass's threshold goes down by 3 with every moved insn). The compiler's reasons here are a hypothesis
(cse replacing `j` by the case's value in the arm; it was measured, not read in the compiler's source).

`variants` rewrites every `switch (V)` with at least three `case N:` arms (decimal or hex integers) whose arms have the
same number of `+ 0xNN` offsets, each with the same base name before it, when for at least one position the arms'
offsets are an arithmetic progression of the case value (`0x418, 0x41C, 0x420`: step 4), into `+ (BASE + V * STEP)`
with BASE the offset the progression has at `V == 0`. The switch's variable must not be assigned inside the switch.
One child with every progression written."""
import re

from .csource import _blank, find

FAMILY = 'arm_index_offsets'
FAMILIES = (FAMILY,)
SWITCH = re.compile(r'\bswitch\s*\(\s*([A-Za-z_]\w*)\s*\)\s*\{')
CASE = re.compile(r'\b(case\s+(0[xX][0-9a-fA-F]+|\d+)\s*:|default\s*:)')
OFFSET = re.compile(r'([A-Za-z_]\w*)\s*\)*\s*\+\s*(0[xX][0-9a-fA-F]{2,})\b')
FIELD = re.compile(r'M2C_FIELD\s*\(\s*([A-Za-z_]\w*)\s*,[^,()]*(?:\([^()]*\)[^,()]*)*,\s*(0[xX][0-9a-fA-F]{2,})\s*\)')


def _block_end(clean, open_at):
    depth = 0
    for at in range(open_at, len(clean)):
        if clean[at] == '{':
            depth += 1
        elif clean[at] == '}':
            depth -= 1
            if depth == 0:
                return at
    return None


def _arms(clean, start, end):
    """[(case value, arm start, arm end)] of the block `clean[start:end]`: the arms at its own nesting level."""
    depth, marks = 0, []
    for at in range(start, end):
        char = clean[at]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 0 and (char == 'c' or char == 'd'):
            hit = CASE.match(clean, at)
            if hit and (at == start or not (clean[at - 1].isalnum() or clean[at - 1] == '_')):
                marks.append((None if hit[2] is None else int(hit[2], 0), at, hit.end()))
    return [(value, body, marks[i + 1][1] if i + 1 < len(marks) else end) for i, (value, _, body) in enumerate(marks)]


def _terms(clean, start, end):
    """The offsets an arm adds to a base: (name of the base, offset, start and end of the literal), in order."""
    found = []
    for hit in OFFSET.finditer(clean, start, end):
        found.append((hit.start(2), hit[1], int(hit[2], 0), hit.start(2), hit.end(2)))
    for hit in FIELD.finditer(clean, start, end):
        found.append((hit.start(2), hit[1], int(hit[2], 0), hit.start(2), hit.end(2)))
    return [(name, value, a, b) for _, name, value, a, b in sorted(found)]


def _progressions(arms):
    """For each position in which every arm's offset follows `base + step * case value`: (position, base, step)."""
    count = len(arms[0][1])
    if count == 0 or any(len(terms) != count for _, terms in arms):
        return []
    out = []
    for position in range(count):
        if len({terms[position][0] for _, terms in arms}) != 1:
            continue
        (v0, t0), (v1, t1) = arms[0], arms[1]
        rise, run = t1[position][1] - t0[position][1], v1 - v0
        if run == 0 or rise % run or rise // run <= 0:
            continue
        step = rise // run
        base = t0[position][1] - step * v0
        if base < 0 or any(terms[position][1] != base + step * value for value, terms in arms):
            continue
        out.append((position, base, step))
    return out


def variants(source, name):
    """One proposal: each progression of a switch's arm offsets written with the switch's own variable."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    edits = []
    for hit in SWITCH.finditer(clean, span[0], span[1]):
        var, open_at = hit[1], hit.end() - 1
        close = _block_end(clean, open_at)
        if close is None or close > span[1]:
            continue
        if re.search(rf'(?<![\w.]){re.escape(var)}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(var)}\b|\b{re.escape(var)}\s*(?:\+\+|--)',
                     clean[open_at:close]):
            continue
        arms = [(value, _terms(clean, a, b)) for value, a, b in _arms(clean, open_at + 1, close) if value is not None]
        if len(arms) < 3 or len({value for value, _ in arms}) != len(arms):
            continue
        for position, base, step in _progressions(arms):
            for value, terms in arms:
                _, _, a, b = terms[position]
                text = f'({var} * {step})' if base == 0 else f'(0x{base:X} + {var} * {step})'
                edits.append((a, b, text))
    if not edits:
        return []
    out = source
    for a, b, text in sorted(set(edits), reverse=True):
        out = out[:a] + text + out[b:]
    return [(FAMILY, out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 62}
