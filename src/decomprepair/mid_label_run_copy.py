"""A label in the middle of a block whose run ends in a `goto`, copied in place of an earlier `goto` to it.

m2c writes a shared push-out tail once, behind a label that follows the other arm's own statements, and sends the
earlier arm there with a `goto`:

    if (d < limit) { ..; p0 += s0; p1 += s1; p2 += s2; goto tail; } } goto next; }
    ..
    f = r - dot; s0 = f * n0; ..; p0 += s0; ..;
    tail: if (flags & 2) { rotate(m, &s0); } out->x += s0; ..; hit = 1; goto next;

The compiler's jump pass (jump.c cross-jumping, after reload) merges two identical runs that end in the same jump, so
a copy written in the earlier arm comes out as the target's `j tail` anyway. What it changes is reload: the copy is
still reloaded before it is deleted, and reload1.c `allocate_reload_reg` hands out the spill registers round robin
(`last_spill_reg`), one turn per reload, in insn order. A copy with an odd number of reloads (a spilled argument's
loads, a constant's register) flips every later `$t1`/`$t2` choice. A 2,267-instruction collision sweep (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O2`) had every spill register from its u8 site's return block on exchanged; the tail copy
(three reloads) turned them back, and the walk after it then needed one turn more, which `loop_break_return` gives
(195 -> 30 with both; the copy alone, 1521, flips the walk's registers the wrong way and moves two float arguments'
global.c tie). So each copy is offered alone and with each of `loop_break_return`'s children.

mid_label_run_copy
    A label preceded by `;` or `}` (not the head of its block), whose run (the statements after it, to the first
    `goto M;` at the label's brace depth) holds no other label, no `return` and no `break`/`continue`: each
    `goto label;` statement outside the run is replaced by the run. The label stays while other `goto`s reach it.
    Children: one per `goto`, each also combined with the `loop_break_return` children of the copied source.
    At most 6.

Candidate rewrites; the exact judge decides each (the rotation is read in reload1.c; the match is one function).
"""
import re

from .flag_exit_repairs import BREAK_RETURN
from .flag_exit_repairs import variants as _flag_exit_variants
from .integer_repair_support import IDENT, view

FAMILY = 'mid_label_run_copy'
FAMILIES = (FAMILY,)
LIMIT = 6
RUN_LIMIT = 4000
_LABEL = re.compile(rf'(?<=[;}}])(\s*)({IDENT})\s*:(?!:)')


def _run(clean, start, end):
    """End offset (after `goto M;`) of the run that starts at start, or None."""
    depth = 0
    i = start
    while i < end:
        ch = clean[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and clean.startswith('goto', i) and not re.match(r'\w', clean[i - 1]):
            hit = re.compile(rf'goto\s+{IDENT}\s*;').match(clean, i)
            if hit:
                return hit.end()
        i += 1
    return None


def _copies(source, part):
    clean = part.clean
    out = []
    for hit in _LABEL.finditer(clean, part.opening + 1, part.end):
        name = hit[2]
        if name in ('default', 'case'):
            continue
        start = hit.end()
        stop = _run(clean, start, part.end)
        if stop is None or stop - start > RUN_LIMIT:
            continue
        run = clean[start:stop]
        if re.search(rf'\b(?:return|break|continue|case|default)\b|(?<![:\w]){IDENT}\s*:(?!:)', run):
            continue
        site_pattern = re.compile(rf'(?<=[;{{}}])(\s*)goto\s+{re.escape(name)}\s*;')
        sites = [m for m in site_pattern.finditer(clean, part.opening, part.end) if not start <= m.start() < stop]
        if not sites:
            continue
        text = source[start:stop].strip()
        for site in sites:
            lo = site.start() + len(site[1])
            edited = source[:lo] + text + source[site.end():]
            if not re.search(rf'goto\s+{re.escape(name)}\s*;', edited):
                edited = re.sub(rf'(?<=[;}}])(\s*){re.escape(name)}\s*:(?!:)', r'\1', edited, count=1)
            out.append(edited)
            if len(out) >= LIMIT:
                return out
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for copy in _copies(source, part):
        out.append((FAMILY, copy))
        for family, child in _flag_exit_variants(copy, name):
            if family == BREAK_RETURN:
                out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring
