"""An if-arm that repeats the statement a goto label already holds, written as a jump to the label.

m2c writes a join as `L: stmt;` at the end of one arm and, in a sibling arm that also ends the same way, nothing but a
`goto L;` or, after its own rewriting, a second copy of `stmt;`. gcc 2.7.2 treats them differently: the copy is a block of
its own that jump.c cross-jumps or leaves in a branch's delay slot, while the jump to the label threads to the one block.
In a 374-instruction N64 effect spawner (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) a `switch` case that tested a
count (`== 1`, `== 2`) and a flag had the arm `if (flag != 1) { rec->byte = 0; } else { goto L_a; }` beside
`L_a: x = 0x3A; L_b: rec->byte = 0;`. The target's code for the arm is `bnel ...; sb $zero` (a likely branch whose delay
slot is the label's store); the copy gave `beql` with the store duplicated behind a `j` (score 1223 -> 392 as the arm
became `goto L_b;`, one of six edits that matched the function; docs/COMPILER_MATCHING_LEARNINGS.md). Hypothesis, not
confirmed in the compiler source: reorg fills the branch's slot from the jump's target when the target is a label with
other uses, and cannot when the block is a private copy.

`arm_label_share` replaces the sole statement of an if-arm `{ stmt; }` with `goto L;` when `L: stmt;` is the last
statement of a sibling arm of the same statement, so both paths run `stmt;` and then reach the same next statement. Only
a simple statement (no goto, return, label or call to the function itself) and arms whose end flows to the same place
(closing braces and else clauses only, never a loop or a switch) qualify. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'arm_label_share'
FAMILIES = (FAMILY,)
LIMIT = 8
LABEL = re.compile(rf'(?<![\w.>:])(?P<label>{IDENT})\s*:(?!:)\s*(?P<statement>[^;{{}}:]+;)')
NOT_LABELS = {'case', 'default', 'else', 'return', 'goto'}


def _python_match(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return None


_match = _python_match
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    pass
else:
    def _match(clean, opening):
        found = _scan.close_if(clean, opening, '{', '}', None)
        return _python_match(clean, opening) if found is NotImplemented else found


def _flow_end(clean, position, limit):
    """Where control goes from `position` (just past a statement) once the closing braces and else clauses are passed.

    Returns the offset of the next statement, or None when a loop or switch body ends on the way."""
    index = position
    while index < limit:
        while index < limit and clean[index].isspace():
            index += 1
        if clean[index:index + 1] == '}':
            opener = _opener(clean, index)
            head = clean[max(0, opener - 160):opener].rstrip() if opener is not None else ''
            if opener is None or re.search(r'\b(?:for|while|switch)\s*\([^{};]*\)$|\bdo$', head):
                return None
            index += 1
        elif clean.startswith('else', index) and not re.match(r'else\w', clean[index:index + 5]):
            index += 4
            while index < limit and clean[index].isspace():
                index += 1
            if clean[index:index + 1] == '{':
                closing = _match(clean, index)
                if closing is None:
                    return None
                index = closing + 1
            else:
                end = clean.find(';', index)
                if end < 0 or '{' in clean[index:end]:
                    return None
                index = end + 1
        else:
            return index
    return index


def _opener(clean, close_at):
    depth = 0
    for index in range(close_at, -1, -1):
        if clean[index] == '}':
            depth += 1
        elif clean[index] == '{':
            depth -= 1
            if depth == 0:
                return index
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean, end = part.clean, part.end
    result = []
    for label in LABEL.finditer(clean, part.opening, end):
        if label['label'] in NOT_LABELS or re.search(r'\b(?:goto|return)\b|\?|\b' + re.escape(name) + r'\b', label['statement']):
            continue
        statement = label['statement'].strip()
        flow = _flow_end(clean, label.end(), end)
        if flow is None:
            continue
        pattern = re.compile(r'{\s*' + re.sub(r'\\\s+', r'\\s*', re.escape(statement)) + r'\s*}')
        for arm in pattern.finditer(clean, part.opening, end):
            if arm.start() <= label.end() <= arm.end() or arm.start() <= label.start() <= arm.end():
                continue
            head = clean[max(0, arm.start() - 160):arm.start()].rstrip()
            if not (head.endswith(')') and re.search(r'\bif\s*\(', head) or head.endswith('else')):
                continue
            if _flow_end(clean, arm.end(), end) != flow:
                continue
            inner = arm.start() + 1
            first = clean.index(statement.split()[0], inner)
            result.append((FAMILY, edit(source, [(first, arm.end() - 1, f'goto {label["label"]};')])))
            if len(result) >= LIMIT:
                return result
    return result
