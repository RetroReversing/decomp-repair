"""A loop's skipped body and its step joined at a label inside a one-pass `do { } while (0)`.

In a `do { if (c) { BODY } i++; } while (n);` loop the skip branch (`beq` on `!c`) goes to the step. GCC 2.7.2's delay-slot
pass (`reorg.c` `fill_eager_delay_slots`) asks `mostly_true_jump` how likely each branch is, and a branch to a label
directly after a `NOTE_INSN_LOOP_BEG` is "the top of a loop": predicted taken (2), so the slot is filled from the
branch target first, with an annulling copy of the step's first insn (`beql ...; addiu $v0,$a0,1`). The plain form is
predicted not taken (`EQ`), the fall-through is tried first, and its first insn (`sll $v0,$v0,2` of the next table
index, harmless to run in the slot) is taken instead: `beq ...; sll`. Nothing in the source changes the instructions,
only which one sits in the slot, so no local edit of the C reads as a fix. Writing the skip as a forward `goto` to a
label that heads a one-pass loop around the step gives the first form:

    if (c) { BODY }  i++;          ->      if (!(c)) goto skip; { BODY }  do { skip: i++; } while (0);

(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, a 143-instruction save-slot function whose third loop skipped one slot;
the same loop had an identical-arm guard `if (t) { A } else { A }` whose branch also ended the fall-through search, so
the wrapper alone left it at 205 against 145, the guard's collapse alone at 300, and both at 60; the swapped bound
compare `comparison_sides` then gave 0. Each step is a loss or neutral alone, so the combination is one child.)

The loop's `do { } while (cond)` body ends with a step `v++;` / `++v;` / `v += 1;` / `v = v + 1;` and the statement
before it is an `if` with a braced body and no `else`. Offered: the wrapper alone (`skip_join_loop_wrapper`) and the
wrapper with every identical-arm guard collapsed first (`skip_join_collapse`). The prediction rule is read in
`reorg.c`; whether the original was written this way is a hypothesis, the exact judge decides."""
import re

from . import identical_arm_collapse_repairs
from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close, negate

FAMILY = 'skip_join_loop_wrapper'
COLLAPSED = 'skip_join_collapse'
FAMILIES = (FAMILY, COLLAPSED)
LIMIT = 6
STEP = re.compile(rf'(?:{IDENT}\s*\+\+|\+\+\s*{IDENT}|{IDENT}\s*\+=\s*1|{IDENT}\s*=\s*{IDENT}\s*\+\s*1)\s*;')


def _python_statements(clean, start, end):
    """(start, end) of each top-level statement of clean[start:end]."""
    out, depth, begin, i = [], 0, None, start
    while i < end:
        ch = clean[i]
        if begin is None and not ch.isspace():
            begin = i
        if ch in '({':
            depth += 1
        elif ch in ')}':
            depth -= 1
            if depth == 0 and ch == '}':
                rest = re.match(r'\s*(else\b|while\b)', clean[i + 1:end])
                if not rest:
                    out.append((begin, i + 1))
                    begin = None
        elif ch == ';' and depth == 0 and begin is not None:
            out.append((begin, i + 1))
            begin = None
        i += 1
    return out


_statements = _python_statements
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _statements(clean, start, end):
        found = _scan.statements_skip_join(clean, start, end)
        return _python_statements(clean, start, end) if found is NotImplemented else found


def _loops(clean, span):
    """(body start, body end) of each `do { ... } while (...)` in the function."""
    for m in re.finditer(r'\bdo\s*\{', clean[span[0]:span[1]]):
        open_at = span[0] + m.end() - 1
        end = close(clean, open_at, '{', '}')
        if end and re.match(r'\s*while\s*\(', clean[end:span[1]]):
            yield open_at + 1, end - 1


def _wrap(source, clean, span, number):
    """The sources with one loop's skipped `if` and step written through a label, one per loop that fits."""
    out = []
    for lo, hi in _loops(clean, span):
        statements = _statements(clean, lo, hi)
        if len(statements) < 2:
            continue
        (a, b), (c, d) = statements[-2], statements[-1]
        step = source[c:d]
        head = re.match(r'if\s*\(', clean[a:b])
        if not head or not STEP.fullmatch(clean[c:d].strip()):
            continue
        paren = a + head.end() - 1
        after = close(clean, paren)
        if not after or not re.match(r'\s*\{', clean[after:b]):
            continue
        block = clean.find('{', after)
        if close(clean, block, '{', '}') != b:
            continue
        if re.search(r'\b(?:continue|break|goto|return)\b', clean[block:b]):
            continue
        condition = source[paren + 1:after - 1].strip()
        negated = negate(condition) or f'!({condition})'
        label = f'skip_join_{number}'
        if re.search(rf'\b{label}\b', source):
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, a) + 1:a])[0]
        head_text = f'if ({negated}) goto {label};\n{indent}'
        tail_text = f'do {{ {label}: {step.strip()} }} while (0);'
        out.append(edit(source, [(a, after, head_text), (c, d, tail_text)]))
    return out


def _collapsed(source, name, header):
    """`source` with every identical-arm guard collapsed (bounded), or None when it has none."""
    current, changed = source, False
    for _ in range(8):
        children = identical_arm_collapse_repairs.variants(current, name, header)
        if not children:
            break
        current, changed = children[0][1], True
    return current if changed else None


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    out = []
    clean = _blank(source)
    for text in _wrap(source, clean, span, 1)[:LIMIT]:
        out.append((FAMILY, text))
    collapsed = _collapsed(source, name, header)
    if collapsed:
        span = find(collapsed, name)
        for text in _wrap(collapsed, _blank(collapsed), span, 1)[:LIMIT]:
            out.append((COLLAPSED, text))
    return [(f, s) for f, s in out if s != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
