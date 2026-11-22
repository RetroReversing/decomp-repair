"""A float constant the target loads inside a loop (`mtc1 $zero, $f0` beside each compare), where ours is hoisted.

KMC GCC 2.7.2 (`-O2 -G0 -mips3 -mgp32 -mfp32`, loop.c): the compare `x >= 0.0f` needs the zero in a register, so
expand makes `(set (reg) (const_double 0))` with a REG_EQUAL note. scan_loop treats it as a movable and
move_movables moves it before the loop when `threshold * savings * lifetime >= insn_count` (threshold =
`(loop_has_call ? 1 : 2) * (1 + n_non_fixed_regs)`, 61 for a loop with a call on this compiler, and 3 less for each
movable moved before it in that loop). A moved constant gets a callee-saved FP register for the whole loop nest
(`mtc1 $zero, $f22` and one more saved register, a bigger frame, every later FP register shifted by one), and once
one inner loop moves it, the enclosing loops move it too (its lifetime is then the span of the whole nest). Equal
constants in sibling loops are combined by combine_movables, so size padding of the inner loops only stops the inner
move, and the group moves out of the middle loop (4 zeros in a 395-insn loop: 61*4*4 >= 395).

What makes the set ineligible, read in scan_loop (confirmed in the 2.7.2 source, `kmc` tree): a pseudo that is not a
user variable is always movable (second `else if`: `! REG_USERVAR_P`), but the pseudo of a *named local* is movable
only when it is set in a block that holds all of its uses (`reg_in_basic_block_p`: `regno_first_uid` is this insn and
`regno_last_uid` is in the same basic block) or the set comes before any label or jump of the loop and the reg is
not used before it. One local `f32 __repair_pin_0;` that carries the constant to every compare, assigned in place
(`x >= (__repair_pin_0 = 0.0f)`), has its first and last reference in different blocks, so loop.c never moves it, at
any loop level; cse still sees the constant at the compare, and nothing is left of the local in the final code:
the zero is loaded where it is used, as the target does. Measured on a ~1000-instruction collision sweep with
seven such compares in six loops: the extra saved FP register, the 8-byte larger frame and the shifted FP
registers disappeared (8632 -> 7018 with nothing else changed; every FP row of the prologue became the target's).

Needs two occurrences of a value in loops (one local reaching two blocks). A value with one occurrence only gets the
form with an initialiser (`f32 __repair_pin_0 = 0.0f;` at the top: its set outside the loop plays the same part;
cse can then take that value for other literal stores of the function, so it is offered second).

Offered as: every repeated value pinned; every value pinned with initialisers; each repeated value alone. A
literal is pinned only as an operand of a comparison or arithmetic operator inside a loop, the places where the
compiler builds the constant in a register (a stored `0.0f` is an integer store and is left alone).
"""
import re

from .csource import _blank, find
from .loop_address_hoist_repairs import _loops
from .pattern_repairs import close

FAMILY = 'float_constant_loop_pin'
FAMILIES = (FAMILY,)
LIMIT = 6
PREFIX = '__repair_pin_'

_FLOAT = re.compile(r'(?<![\w.])(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?[fF]?(?![\w.])')
_RELATIONAL = ('<=', '>=', '==', '!=', '<', '>')
_ARITHMETIC = ('+', '-', '*', '/')


def _left_operator(clean, at):
    """The operator just before position `at` when it makes the literal a plain operand, else ''."""
    i = at
    while i > 0 and clean[i - 1].isspace():
        i -= 1
    for op in _RELATIONAL:
        if clean[:i].endswith(op) and not (op in '<>' and clean[:i].endswith(('<<', '>>', '->'))):
            return op
    if i and clean[i - 1] in '*/':
        return clean[i - 1]
    if i and clean[i - 1] in '+-' and not clean[:i].endswith(('++', '--', '+=', '-=', '->')):
        before = clean[:i - 1].rstrip()
        if before and (before[-1].isalnum() or before[-1] in '_)]'):
            return clean[i - 1]  # binary, not a sign
    return ''


def _right_operator(clean, at):
    i = at
    while i < len(clean) and clean[i].isspace():
        i += 1
    rest = clean[i:i + 2]
    for op in _RELATIONAL:
        if rest.startswith(op) and not rest.startswith(('<<', '>>')):
            return op
    if rest[:1] in ('*', '/') and rest[1:2] != '=':
        return rest[0]
    if rest[:1] in ('+', '-') and rest[1:2] not in ('=', rest[:1], '>'):
        return rest[0]
    return ''


def _occurrences(clean, spans):
    """{literal text: [(start, end)]} for the float literals inside loops that are operands of an operator."""
    found = {}
    for start, end in spans:
        for m in _FLOAT.finditer(clean, start, end):
            if not (_left_operator(clean, m.start()) or _right_operator(clean, m.end())):
                continue
            found.setdefault(m.group(), []).append((m.start(), m.end()))
    # a nested loop is inside its outer one: the same literal may have been found twice
    return {text: sorted(set(places)) for text, places in found.items()}


def _kind(text):
    return 'f32' if text[-1] in 'fF' else 'f64'


def _apply(chosen, initial):
    """`source` with each literal in `chosen` (text -> places) written `(__repair_pin_N = literal)` and the locals declared."""
    edits, declarations = [], []
    for number, (text, places) in enumerate(chosen.items()):
        name = f'{PREFIX}{number}'
        declarations.append(f'{_kind(text)} {name}' + (f' = {text}' if initial else '') + ';')
        edits.extend((start, end, f'({name} = {text})') for start, end in places)
    return edits, declarations


def _build(source, opening, edits, declarations):
    edits = sorted(edits, reverse=True)
    for start, end, new in edits:
        source = source[:start] + new + source[end:]
    shift = sum(len(new) - (end - start) for start, end, new in edits if start < opening)
    point = opening + shift + 1
    return source[:point] + '\n    ' + '\n    '.join(declarations) + source[point:]


def variants(source, name, asm=None):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or PREFIX in clean:
        return []
    if asm is not None and not re.search(r'\bmtc1\b', asm):
        return []  # no float constant is built in a register by the target
    loops = _loops(clean, opening, end)
    if not loops:
        return []
    found = _occurrences(clean, loops)
    repeated = {text: places for text, places in found.items() if len(places) >= 2}
    results = []

    def add(chosen, initial):
        if not chosen:
            return
        edits, declarations = _apply(chosen, initial)
        text = _build(source, opening, edits, declarations)
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))

    add(repeated, False)
    add(found, True)
    if len(repeated) > 1:
        for text, places in repeated.items():
            add({text: places}, False)
    return results[:LIMIT]
