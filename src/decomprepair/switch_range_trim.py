"""A switch's jump table as narrow as the target's range check: the labels beyond it written out of the source.

gcc builds a jump table over the cases' lowest to highest value, so every `case N:` label that only falls into
`default:` widens it: `case 0: case 1: ... case 45: ... case 50: default:` is a table over 0..50 and a bound check
`sltiu $v0, $v1, 0x33`, where the game's check was `addiu $v1, $v0, -2; sltiu $v0, $v1, 0x2b` (2..44). An m2c draft
(and an agent trying every value the arms could see) lists the values around the cases; the game's source named only
the ones in its range. `switch_range` adds labels the target's range reaches beyond the cases; this is the other way
round: the aliases of `default:` outside the target's range are removed, and the table, its bound and the register the
index is computed in all follow, so the arms' jump-table entries (one word of `.rodata` each) agree with the target's.

A KMC GCC 2.7.2 N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`, 713 instructions) had `case 0: case 1:` and
`case 45:` to `case 50:` before the `default:` of its second switch: the bound check and the index's `addiu` were
the two rows left in that switch and its whole table (43 entries) was one word out of place (2270 -> 2015 with the
other steps of the chain; alone it scored 2465 against 2420, as the table was right and the code before it not).

`variants` takes each `switch` that has a `default:` and, immediately before it, a run of empty `case N:` labels, and for
each range check the target has (`switch_range_repairs.ranges`: the lowest value and the count of an `sltiu`, with the
`addiu` that biases the index) that spans every other label of the switch, removes the labels of the run that are outside
it. The labels inside the range stay (they are the table's ends). One child per check, at most 2. Each is offered
again with the function's `volatile` casts written plain (`volatile_cast_unpin`, as `switch_range_trim_unpin`): in the
spawner's chain, once its first switch's arms were right (415), the trim alone was 460, the plain read alone 555 and the
two together 0. The `nop` that a `volatile` load leaves in a branch's delay slot is one word, and it moves every entry
of the second switch's table the way the extra labels move its range; neither half alone puts the 43 entries back."""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .switch_range_repairs import NUMBER, ranges
from .volatile_cast_unpin import variants as unpinned

FAMILY = 'switch_range_trim'
UNPIN = 'switch_range_trim_unpin'
FAMILIES = (FAMILY, UNPIN)
LIMIT = 2


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    checks = ranges(asm)
    if not end or not checks:
        return []
    result = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        head = opening + switch.end() - 1
        block_open = clean.find('{', close(clean, head) or head)
        block_close = close(clean, block_open, '{', '}') if block_open >= 0 else None
        if not block_close:
            continue
        default = re.search(r'\bdefault\s*:', clean[block_open:block_close])
        if not default:
            continue
        # the run of empty case labels that ends at the `default:`
        before = clean[block_open:block_open + default.start()]
        run = re.search(r'(?:\bcase\s+' + NUMBER + r'\s*:\s*)+$', before)
        if not run:
            continue
        labels = list(re.finditer(r'\bcase\s+(' + NUMBER + r')\s*:\s*', run[0]))
        before_run = re.findall(r'\bcase\s+(' + NUMBER + r')\s*:', clean[block_open:block_open + run.start()])
        bodies = [int(v, 0) for v in before_run] + [int(v, 0) for v in re.findall(r'\bcase\s+(' + NUMBER + r')\s*:', clean[block_open + default.end():block_close])]
        for start, count in checks:
            top = start + count - 1
            if any(not start <= value <= top for value in bodies):
                continue  # a check that does not span this switch's other cases is another switch's
            outside = [hit for hit in labels if not start <= int(hit[1], 0) <= top]
            if not outside or len(outside) == len(labels):
                continue
            offset = block_open + run.start()
            text = source
            for hit in sorted(outside, key=lambda hit: -hit.start()):
                text = text[:offset + hit.start()] + text[offset + hit.end():]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
    result = result[:LIMIT]
    for _, text in list(result):
        for _, plain in unpinned(text, name)[:1]:
            result.append((UNPIN, plain))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 60}  # the registry: no caller wiring (registry.py)
