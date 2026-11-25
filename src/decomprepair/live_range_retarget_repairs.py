"""One short live range of a local given to another local that is free there.

GCC 2.7 makes one pseudo of every source variable, however many unrelated values it holds, and the allocator treats
the union of its ranges as one. m2c reuses one name for values that have nothing to do with each other: here `low`
holds the found flag's copy for one test and, much later, the masked word that is passed to a call. A pseudo that is
copied into an argument register for a call prefers that register (`$a0`); the flag's copy took it too, and the
allocator, which gives a copy the register of its source when the two do not overlap, then deleted the move that the
target keeps (`move $v0,$a0; bnez $v0`, where the copy is a block-local temporary in `$v0`). Writing the first
range through another local that is free over it, one that is no call argument, gave the target's move (a 180-instruction
N64 function, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`: 501 -> 285 with the loop's limit local `end`, 295 with
three other locals; `disjoint_local_merge` merges the whole variable and scored 566).

For each integer local assigned more than once (so it holds at least two values), each of its ranges that is a plain
assignment followed by at most five statements that use it before the next assignment is offered written through
each other integer local `X` that is not mentioned in the range and whose next mention after the range is an
assignment. The candidates are ranked by how near `X`'s next mention is. A candidate for the exact judge, never a
verdict."""
import re

from .integer_repair_support import locals_for
from .line_scan import apply, lines, mentions

FAMILIES = ('live_range_retarget',)
LIMIT = 16
SPAN = 5  # the most statements a range may hold after its assignment
WIDTH = {'s32', 'u32', 'int', 'unsigned int', 'unsigned'}


def _assigns(text, name):
    return re.match(rf'\s*{re.escape(name)}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)', text) is not None


def _leaves_block(region):
    """The range closes the block its assignment is in: the value then meets another path's value at a join."""
    depth = 0
    for line in region[1:]:
        for char in line.stripped:
            depth += {'{': 1, '}': -1}.get(char, 0)
            if depth < 0:
                return True
    return False


def _dead_after(body, start, stop, var):
    """The range's value is not read after it. A plain assignment at the depth of the range's own one ends the search; one
    nested deeper (inside an `if` or a loop opened since) covers only the reads inside its block, so a read after that
    block closes may still see the range's value (a clamp's `if (x < 0) { x = 0; }` and the `if (x >= 0x100)` after it)."""
    depth, kill = 0, None
    for at, line in enumerate(body[start + 1:], start + 1):
        text = line.stripped
        if at > stop and mentions(text, var):
            plain = re.match(rf'{re.escape(var)}\s*=(?!=)', text) is not None and not mentions(text.split('=', 1)[1], var)
            if plain and depth <= 0:
                return True
            if plain:
                kill = depth if kill is None else min(kill, depth)
            elif kill is None or depth < kill:
                return False
        for char in text:
            depth += {'{': 1, '}': -1}.get(char, 0)
            if kill is not None and depth < kill:
                kill = None
    return True


def variants(source, name):
    from .integer_repair_support import view
    part = view(source, name)
    if not part:
        return []
    decls = {d['name']: d for d in locals_for(part) if ' '.join(d['type'].split()) in WIDTH}
    if len(decls) < 2:
        return []
    body = lines(part, source)
    out = []
    for var in decls:
        defs = [i for i, line in enumerate(body) if line.stripped.endswith(';') and re.match(rf'{re.escape(var)}\s*=(?!=)', line.stripped)
                and not mentions(line.stripped.split('=', 1)[1], var)]
        if len(defs) < 2:
            continue
        for i in defs:
            stop = i
            for j in range(i + 1, min(len(body), i + 1 + SPAN + 8)):
                text = body[j].stripped
                if _assigns(text, var):
                    break
                if mentions(text, var):
                    stop = j
                if text in ('}', '{') and stop == i:
                    continue
            if stop == i or stop - i > SPAN:
                continue
            region = body[i:stop + 1]
            if any(re.match(r'(?:while|do)\b', line.stripped) for line in region):
                continue
            if _leaves_block(region) or not _dead_after(body, i, stop, var):
                continue
            for other in decls:
                if other == var or any(mentions(line.stripped, other) for line in region):
                    continue
                after = next((k for k in range(stop + 1, len(body)) if mentions(body[k].stripped, other)), None)
                if after is not None and not _assigns(body[after].stripped, other):
                    continue
                if after is None:
                    continue
                edits = []
                for line in region:
                    for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', line.text):
                        edits.append((line.start + m.start(), line.start + m.end(), other))
                out.append((after - stop, i, other, apply(source, edits)))
    out.sort(key=lambda item: item[:3])
    return [(FAMILIES[0], text) for _, _, _, text in out[:LIMIT] if text != source]
