"""The statements after a two-arm `if`/`else` whose arms end with the same call, written at the end of both arms.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) 1445-instruction collision query (four triangle loops, each
with a plane arm and a closest-edge arm that both end `rotate(matrix, correction);`, then add the correction to the
caller's position, set the hit flag and mark the actor). Written once after the `if`/`else`, the tail's three loads and
three stores through the position parameter are counted once per loop; the parameter (live through the whole
function, 1100+ insns) then ranked below the actor cursor in global.c (`floor_log2 (refs) * refs / live`: 0.59
against 0.84) and the two swapped saved registers in every block. Written in both arms (the target's jump2
cross-jumps the identical tails back into one copy after allocation, so the object code is the same length), the
parameter's weighted references rise from 112 to 208 (priority 1.20 > 0.97) and every block takes the target's
registers: 5082 -> 4828 on its own, and the step that let the rest of that match go to 0.

else_tail_into_arms
    `if (c) { ...; f(x); } else { ...; f(x); } T` (T running to the end of the enclosing block) becomes
    `if (c) { ...; f(x); T } else { ...; f(x); T }` when both arms end with the same call statement, T is one or more
    plain statements (no labels, `case`, declarations or `return` of a value read in the arms), and T is not too long.
    The reference weighting is read from flow.c (`reg_n_refs += loop_depth`) and global.c's priority; that the
    target's tail was written twice is a hypothesis the cross-jump makes indistinguishable from the object code.

The exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'else_tail_into_arms'
FAMILIES = (FAMILY,)
LIMIT = 6
MAX_TAIL_LINES = 40


def _python_open_of(clean, closing):
    """Position of the `{` that matches the `}` at `closing`, scanning backwards."""
    depth = 0
    for pos in range(closing, -1, -1):
        char = clean[pos]
        if char == '}':
            depth += 1
        elif char == '{':
            depth -= 1
            if depth == 0:
                return pos
    return None


_open_of = _python_open_of
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _open_of(clean, closing):
        found = _scan.open_if(clean, closing, '{', '}', None)
        return _python_open_of(clean, closing) if found is NotImplemented else found


def _python_block_end(clean, start, limit):
    """Position of the `}` that closes the block containing `start`."""
    depth = 0
    for hit in re.finditer(r'[{}]', clean[start:limit]):
        if hit[0] == '{':
            depth += 1
        elif depth == 0:
            return start + hit.start()
        else:
            depth -= 1
    return None


_block_end = _python_block_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_end(clean, start, limit):
        found = _scan.enclosing_end(clean, start, limit, None)
        return _python_block_end(clean, start, limit) if found is NotImplemented else found


def _last_statement(arm):
    """The last top-level statement of an arm's text (without its braces), or None."""
    text = arm.rstrip()
    if not text.endswith(';'):
        return None
    depth, start = 0, 0
    for pos, char in enumerate(text[:-1]):
        if char in '({':
            depth += 1
        elif char in ')}':
            depth -= 1
        elif char == ';' and depth == 0:
            start = pos + 1
    if text.rfind('}') > start:
        start = text.rfind('}') + 1
    return text[start:].strip()


def _indent(text, extra):
    return ''.join((extra + line if line.strip() else line) for line in text.splitlines(True))


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for hit in re.finditer(r'\belse\s*\{', clean[part.opening + 1:part.end]):
        else_open = part.opening + 1 + hit.end() - 1
        else_close = close(clean, else_open, '{', '}')
        if else_close is None:
            continue
        before = clean[:part.opening + 1 + hit.start()].rstrip()
        if not before.endswith('}'):
            continue
        then_close = len(before) - 1
        then_open = _open_of(clean, then_close)
        if then_open is None or then_open <= part.opening:
            continue
        head = clean[:then_open].rstrip()
        if not head.endswith(')'):
            continue
        then_arm, else_arm = clean[then_open + 1:then_close], clean[else_open + 1:else_close - 1]
        last_then, last_else = _last_statement(then_arm), _last_statement(else_arm)
        if not last_then or last_then != last_else or not re.match(rf'{IDENT}\s*\(', last_then):
            continue
        end = _block_end(clean, else_close, part.end)
        if end is None:
            continue
        tail = clean[else_close:end]
        if not tail.strip() or not tail.rstrip().endswith((';', '}')):
            continue
        if (tail.count('\n') > MAX_TAIL_LINES
                or re.search(rf'(?m)^\s*{IDENT}\s*:(?!:)|\b(?:case|default|goto|return)\b', tail)
                or re.search(rf'(?m)^\s*(?:const\s+)?(?:struct\s+)?{IDENT}\s+\**\s*{IDENT}\s*(?:\[[^\]]*\])?\s*;', tail)):
            continue
        original = source[else_close:end]
        lines = original.strip('\n')
        if not lines.strip():
            continue
        arm_tail = '\n' + _indent(lines, '  ').rstrip() + '\n'
        then_ws = source[source.rfind('\n', 0, then_close) + 1:then_close]
        else_ws = source[source.rfind('\n', 0, else_close - 1) + 1:else_close - 1]
        if then_ws.strip() or else_ws.strip():
            continue
        line_start = source.rfind('\n', 0, then_close) + 1
        else_line = source.rfind('\n', 0, else_close - 1) + 1
        tail_start = else_close
        edits = [
            (line_start - 1, line_start - 1, arm_tail.rstrip('\n')),
            (else_line - 1, else_line - 1, arm_tail.rstrip('\n')),
            (tail_start, end, '\n' + source[source.rfind('\n', 0, end) + 1:end] if '\n' in original else ''),
        ]
        # The last edit keeps the closing brace's own indentation on its line.
        result.append((FAMILY, edit(source, edits)))
        if len(result) >= LIMIT:
            break
    return result


def variants(source, name, header=''):
    out = _children(source, name)
    if len(out) > 1:
        # Every eligible join at once: the parameter's weight only moves when all the copies are written.
        combined = source
        for _ in range(LIMIT):
            step = _children(combined, name)
            if not step:
                break
            combined = step[0][1]
        if combined not in [text for _, text in out]:
            out.append((FAMILY, combined))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
