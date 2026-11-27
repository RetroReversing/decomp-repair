"""A sparse `switch` renumbered from zero, so its cases are dense and gcc emits a jump table.

KMC GCC 2.7.2 builds a jump table only when the labels fill enough of their range; `switch (x)` over 1, 2, 3, 4 and 11
(plus a `case 0:` that falls into `default:`) is a compare tree. The game's table (`addiu $v1, $v0, -1; sltiu $v0, $v1,
11; beqz`) was a switch over `x - 1`, labels 0..10, and the values between its used labels (4..9) written out as empty
`case N: break;` arms, so every index in the range has an entry and the bound check is the range's. A N64 state routine
(135 instructions, `-G0 -mips3 -mgp32 -mfp32 -O1 -g`) stood at 555 with the sparse form and was exact with the offset
form (the labels it needed were `case 0` for the old 1, `case 4`..`case 9` empty, `case 10` for the old 11; the old
`case 0:` alias of `default:` is dropped, since its value is now out of the range and goes to the default by itself).
`switch_range` adds labels to the default arm for a range that the cases do not reach; this one changes the
discriminant, so it is a different shape, and the gap labels may go to the end of the switch instead of the default.

Each `switch` with a `default:` whose labels (the empty run of aliases before the `default:` aside) fill exactly the
target's range check (`switch_range_repairs.ranges`: a biased `sltiu`, bias above zero) becomes `switch (x - bias)` with
every label lowered by the bias and the aliases outside the range removed. Children, per check (at most 2 checks):
the values the cases miss written as `case N:` labels of one empty `break;` arm at the end of the switch, and the same
labels on the default arm. A switch with a nested `switch`, or whose discriminant already subtracts a constant, is left
alone. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .switch_range_repairs import NUMBER, ranges

FAMILY = 'switch_offset_table'
FAMILIES = (FAMILY,)
LIMIT = 4
_LABEL = re.compile(r'\bcase\s+(' + NUMBER + r')\s*:')
_ALIASES = re.compile(r'((?:\bcase\s+' + NUMBER + r'\s*:\s*)+)(?=default\s*:)')


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    checks = [(low, count) for low, count in ranges(asm) if low > 0 and count > 2]
    if not end or not checks:
        return []
    result = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        head = opening + switch.end() - 1
        head_end = close(clean, head)
        block_open = clean.find('{', head_end or head)
        block_end = close(clean, block_open, '{', '}') if block_open >= 0 and head_end else None
        if not block_end:
            continue
        block = clean[block_open:block_end]
        expression = source[head + 1:head_end - 1].strip()
        if re.search(r'\bswitch\b', block) or re.search(r'-\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*$', expression):
            continue
        default = re.search(r'(?m)^([ \t]*)default\s*:', block) or re.search(r'default\s*:', block)
        if not default or not expression:
            continue
        aliases = _ALIASES.search(block)
        alias_span = (aliases.start(1), aliases.end(1)) if aliases else (0, 0)
        labels = [hit for hit in _LABEL.finditer(block)]
        for start, count in checks[:2]:
            top = start + count - 1
            inside = [hit for hit in labels if start <= int(hit[1], 0) <= top]
            outside = [hit for hit in labels if not start <= int(hit[1], 0) <= top]
            if any(not (alias_span[0] <= hit.start() and hit.end() <= alias_span[1]) for hit in outside):
                continue
            values = {int(hit[1], 0) for hit in inside}
            if not values or min(values) != start or max(values) != top:
                continue
            gaps = [v for v in range(start, top + 1) if v not in values]
            indent = (re.search(r'(?m)^([ \t]*)case\b', block) or default)[1] if re.search(r'(?m)^([ \t]*)case\b', block) else '    '
            edits = [(head + 1, head_end - 1, expression + ' - ' + str(start) if re.fullmatch(r'\w+', expression)
                      else '(' + expression + ') - ' + str(start))]
            for hit in outside:
                edits.append((block_open + hit.start(), block_open + hit.end(), ''))
            for hit in inside:
                edits.append((block_open + hit.start(1), block_open + hit.end(1), str(int(hit[1], 0) - start)))
            for where in ('end', 'default'):
                if not gaps and where == 'default':
                    continue
                text = list(edits)
                if gaps and where == 'end':
                    labels_text = ''.join(f'{indent}case {v - start}:\n' for v in gaps)
                    at = source.rfind('\n', 0, block_end - 1) + 1
                    at = at if not source[at:block_end - 1].strip() else block_end - 1
                    text.append((at, at, labels_text + f'{indent}    break;\n'))
                elif gaps:
                    labels_text = ''.join(f'{indent}case {v - start}:\n' for v in gaps)
                    at = block_open + default.start()
                    at = source.rfind('\n', 0, at) + 1 if source[source.rfind('\n', 0, at) + 1:at].strip() == '' else at
                    text.append((at, at, labels_text))
                out = source
                for a, b, new in sorted(text, key=lambda e: (-e[0], -e[1])):
                    out = out[:a] + new + out[b:]
                if out != source and out not in [t for _, t in result]:
                    result.append((FAMILY, out))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 61}
