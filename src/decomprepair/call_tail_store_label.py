"""Stores after an arm's last call moved into a block of their own that the arm jumps to.

An arm that ends `requestSound(0xFF); rec->field = 0.0f; goto join;` gives GCC 2.7.2's first scheduler (`sched.c`,
backward list scheduling) a block whose tail is only the `goto`: every insn ahead of it is free to sink past the call,
and a copy whose source was computed by a multiply (`var_s6 = var_fs3;` after `var_fs3 *= cosAngle(..)`) carries the
multiply's latency in its priority, so it is scheduled first and lands after the call (`jal; sb; mfc1 $s6,$f26; j`).
`schedule_block` keeps calls, jumps and `use`s that end a block "in order at the end of the block" and makes every
other insn depend on the first of them: when the call is the last insn before the jump, the copy stays above it. The
store that followed the call came from a block of its own the arm jumped to (`goto clear; ... clear: rec->field = 0;
join:`), and reorg later fills the jump's delay slot with that store and threads the jump past it, so the target reads
`mfc1 $s6,$f26; nop; jal; sb (slot); j join; sw $zero (slot)`: the same instructions as the one-block form with the
copy above the call (KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O2`, a 3034-instruction actor-motion handler: 140 -> 20
with this alone, two `o` row pairs gone).

For each statement-level call followed by one to four plain statements without calls and then `goto L;`, the child
replaces those statements with `goto L_tail;` and writes `L_tail: <statements>` right above `L:` (after a `goto L;` so
whatever fell through to `L` still skips them). The program is the same program; only the blocks differ. Statements
that mention a label, `return`, `break`, `continue`, `case`, `default`, braces or a call are not moved. Proposals only;
the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit

FAMILY = 'call_tail_store_label'
FAMILIES = (FAMILY,)
LIMIT = 8
MAX_STATEMENTS = 4

CALL = re.compile(rf'(?m)^[ \t]*(?:\(void\)\s*)?{IDENT}\s*\([^;{{}}]*\)\s*;[ \t]*\n')
STATEMENT = re.compile(r'[ \t]*(?P<text>[^;{}\n]+;)[ \t]*\n')
GOTO = re.compile(rf'[ \t]*goto\s+(?P<label>{IDENT})\s*;')
KEYWORDS = re.compile(r'\b(?:return|break|continue|case|default|goto|if|else|while|for|do|switch)\b')


def _plain(text):
    """A statement that only computes and stores: no call, no control flow, no label."""
    if KEYWORDS.search(text) or re.match(rf'\s*{IDENT}\s*:(?!:)', text):
        return False
    # A call is a name followed by `(`, or `(*f)(`; a cast such as `(f32 *) (p + 4)` is not.
    if re.search(r'\(\s*\*\s*\w+\s*\)\s*\(', text):
        return False
    return not any(hit.group(1) != 'sizeof' for hit in re.finditer(rf'(?<![\w.])({IDENT})(?=\s*\()', text))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    lo, hi = span
    clean = _blank(source)
    opening = clean.find('{', lo)
    if opening < 0 or opening >= hi:
        return []
    body = clean[opening:hi]
    labels = {m.group(1): opening + m.start() for m in re.finditer(rf'(?m)^[ \t]*({IDENT})\s*:(?!:)', body)
              if m.group(1) not in ('default',)}
    used = set(re.findall(IDENT, body))
    result = []
    for call in CALL.finditer(clean, opening, hi):
        at = call.end()
        moved = []
        while len(moved) < MAX_STATEMENTS:
            stmt = STATEMENT.match(clean, at)
            if not stmt or GOTO.match(clean, at) or not _plain(stmt['text']):
                break
            moved.append((stmt.start(), stmt.end()))
            at = stmt.end()
        jump = GOTO.match(clean, at)
        if not moved or not jump or jump['label'] not in labels:
            continue
        label = jump['label']
        target = labels[label]
        if moved[0][0] <= target < at:
            continue
        fresh = f'{label}_tail'
        index = 2
        while fresh in used:
            fresh = f'{label}_tail{index}'
            index += 1
        text = ''.join(source[s:e].strip() + ' ' for s, e in moved).rstrip()
        indent = re.match(r'[ \t]*', source[moved[0][0]:]).group()
        line = source.rfind('\n', 0, target) + 1
        outer = re.match(r'[ \t]*', source[line:]).group()
        edits = [(moved[0][0], jump.end(), f'{indent}goto {fresh};'),
                 (line, line, f'{outer}goto {label};\n{outer}{fresh}:\n{indent}{text}\n')]
        child = edit(source, edits)
        if child != source and child not in [c for _, c in result]:
            result.append((FAMILY, child))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
