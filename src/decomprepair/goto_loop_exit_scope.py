"""A backward-`goto` loop's exit branch: the pointer step moved into the body and the loop wrapped in `do { } while (0)`.

m2c writes a scan that walks a table as a label and a `goto`:

    loop: if (((u16) (*(p--))) >= t) { idx -= 1; goto loop; }

and the step `p--` sits in the condition, ahead of the exit branch. KMC gcc 2.7.2 (reorg.c, the delay-slot pass) read
this way in the app's own cc1, traced with a debugger and read in the compiler's source:

1. `p--` is an insn before the branch. The first pass (fill_simple_delay_slots) moves it into the branch's delay slot
   from above and leaves a `(use (insn))` marker where it was (update_block). The second pass
   (fill_eager_delay_slots) then asks, for an EARLIER loop's back branch, which registers are live at its fall-through
   (mark_target_live_regs); the scan reaches the marker and adds the pointer's register as live. When that is the
   register of the earlier loop's counter (its delay-slot insn is the copy of the loop head `next = i + 1`), the slot
   needs an annulling `bnel` instead of the game's plain `bnez`.
2. With the step in the body (`if (*p >= t) { p--; idx -= 1; goto loop; }`) the step is the exit branch's fall-through
   thread and no marker lies on the straight line from the earlier loop, so the back branch gets its plain `bnez`.
3. Which thread fills the exit branch's slot is decided by mostly_true_jump: a jump that leaves a loop (a label
   outside the enclosing LOOP_BEG/LOOP_END notes, `LABEL_OUTSIDE_LOOP_P`, set in loop.c) predicts "not taken", so the
   fall-through thread is tried first and the step goes into the slot (`bnez exit; addiu p, p, -2`). A goto loop has no
   loop notes, so the exit branch predicts "taken" and an independent insn from the exit block (`sll`) is pulled into
   the slot instead. A `do { } while (0)` round the label and its `if` gives the loop its notes (and no back edge), and
   nothing else changes.

The three together are the shape of a two-arm table search (two such scans, each after a `do { ... } while` that counts
a bit length) that went 525 -> 245 (the step in the body) -> 110 (the wrapper) and then 0 with a per-arm base pointer
(`arm_private_rename`). Alone the wrapper scored 230 and the step 245, so both are offered together as one child, and
each alone.

Proposed per loop (a label alone on its line, an `if` whose block ends in `goto label;`), only when the label is
jumped to from nowhere else, and for the step only when the pointer is not read after the loop before it is set again.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'goto_loop_exit_scope'
FAMILIES = (FAMILY,)
LIMIT = 24

_ID = r'[A-Za-z_]\w*'
_STEP = re.compile(rf'\*\s*\(\s*({_ID})\s*(--|\+\+)\s*\)|\*\s*({_ID})\s*(--|\+\+)')
_LOOP = re.compile(rf'(?m)^([ \t]*)({_ID}):[ \t]*\n[ \t]*if\s*\(')


class _Loop:
    def __init__(self, label, start, cond, block, end, indent):
        self.label, self.start, self.cond, self.block, self.end, self.indent = label, start, cond, block, end, indent


def _loops(source, name):
    """(clean, opening, end, [loops]) of the function: each `label: if (cond) { ...; goto label; }` on its own."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    found = []
    for hit in _LOOP.finditer(clean, opening, end):
        paren = hit.end() - 1
        cond_end = close(clean, paren, '(', ')')
        if not cond_end:
            continue
        brace = re.compile(r'\s*\{').match(clean, cond_end)
        if not brace:
            continue
        open_at = brace.end() - 1
        block_end = close(clean, open_at, '{', '}')
        if not block_end:
            continue
        label = hit[2]
        if not re.search(rf'goto\s+{label}\s*;\s*\}}$', clean[open_at:block_end]):
            continue
        if re.match(r'\s*else\b', clean[block_end:end]):
            continue
        # the label is jumped to from this loop only
        if len(re.findall(rf'(?<![\w.>]){label}\b', clean[opening:end])) != 2:
            continue
        found.append(_Loop(label, hit.start(), (paren, cond_end), (open_at, block_end), block_end, hit[1]))
    return clean, opening, end, found


def _wrapped(clean, loop):
    """True when the loop already sits in a one-statement `do { } while (0);`."""
    before = clean[:loop.start].rstrip()
    after = clean[loop.end:]
    return before.endswith('do {') and re.match(r'\s*\}\s*while\s*\(\s*0\s*\)\s*;', after) is not None


def _step_edit(source, clean, end, loop):
    """The edits that take `*(p--)` out of the loop's condition and put `p--;` first in its block, or None."""
    cond = clean[loop.cond[0] + 1:loop.cond[1] - 1]
    steps = list(_STEP.finditer(cond))
    if len(steps) != 1:
        return None
    step = steps[0]
    pointer = step[1] or step[3]
    sign = step[2] or step[4]
    if len(re.findall(rf'(?<![\w.>]){pointer}\b', cond)) != 1:
        return None
    # no read of the pointer after the loop before it is set again: the exit no longer steps it
    after = list(re.finditer(rf'(?<![\w.>]){pointer}\b', clean[loop.end:end - 1]))
    if after:
        nxt = after[0]
        tail = clean[loop.end + nxt.end():end]
        if not re.match(r'\s*=(?!=)', tail):
            return None
        stmt_end = clean.find(';', loop.end + nxt.end())
        if stmt_end < 0 or re.search(rf'(?<![\w.>]){pointer}\b', clean[loop.end + nxt.end():stmt_end]):
            return None
    at = loop.cond[0] + 1
    replaced = f'*{pointer}'
    indent = loop.indent + '  '
    return [(at + step.start(), at + step.end(), replaced),
            (loop.block[0] + 1, loop.block[0] + 1, f'\n{indent}{pointer}{sign};')]


def _apply(source, edits):
    out = source
    for lo, hi, text in sorted(edits, reverse=True):
        out = out[:lo] + text + out[hi:]
    return out


def _wrap_edit(loop):
    """The edits that wrap the loop (label line to the closing brace) in `do { } while (0);`."""
    return [(loop.start, loop.start, f'{loop.indent}do {{\n'), (loop.end, loop.end, f'\n{loop.indent}}} while (0);')]


def variants(source, name):
    """[(FAMILY, source)]: the step in the body and the wrapper together for every loop first (the step and the wrapper
    each score worse than that alone), then each loop with both, with the step, with the wrapper, then all of either."""
    part = _loops(source, name)
    if not part:
        return []
    clean, opening, end, loops = part
    if not loops:
        return []
    steps = {i: _step_edit(source, clean, end, loop) or [] for i, loop in enumerate(loops)}
    wraps = {i: [] if _wrapped(clean, loop) else _wrap_edit(loop) for i, loop in enumerate(loops)}
    out = []

    def add(edits):
        text = _apply(source, edits)
        if edits and text != source and all(text != other for _, other in out):
            out.append((FAMILY, text))

    every_step = [e for i in steps for e in steps[i]]
    every_wrap = [e for i in wraps for e in wraps[i]]
    add(every_step + every_wrap)
    for i in range(len(loops)):
        add(steps[i] + wraps[i])
    for i in range(len(loops)):
        add(steps[i])
        add(wraps[i])
    add(every_step)
    add(every_wrap)
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
