"""A halfword call result held in a `u16` local, and the sum around it staged: m2c's `((u16) f()) * 8` spelled as the game did.

m2c writes a call's halfword result where it is used, `g(off + ((u16) f()) * 8 + &table)`. The compiler then widens the
result right after the call (`andi $v0,$v0,0xffff`) and schedules it ahead of the arithmetic on the other addend, while
the target computes the other addend first and widens the result later. Held in a `u16` local, `t = f();`, the
value is only widened where it is used (a halfword pseudo is widened at its use), and the other addend, staged in a
local of its own after the call, is computed ahead of that. The sum is then written through the file's inline add helper
(`H(t * 8 + &table, off)`), which stops the compiler's own associating of the table's address with the other addend
(`(off + &table) + t * 8`), the way `add_helper_operand_swap` and m2c's other helpers do. On a KMC
`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2` menu-update function the two last rows of a 394-instruction difference
needed all three edits (10 -> 0); each alone left them: the hoist alone, or the addend staged with a plain `+`, scored 10 and 5.

Offered per statement whose real call takes one argument `L + R`, where one operand holds exactly one `((u16) f(...))`
and the other is free of calls but inline helpers: `call_result_halfword_local` (the hoist), `call_result_sum_stage` (the
hoist and the other addend staged, joined by a plain `+`) and `call_result_sum_helper` (the same joined by the inline add
helper, in both argument orders). The statement must not contain a real call before the one hoisted, except calls that
enclose it. A candidate for the exact judge, never a verdict."""
import re

from .add_helper_operand_swap import _helpers
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

HOIST = 'call_result_halfword_local'
STAGE = 'call_result_sum_stage'
HELPER = 'call_result_sum_helper'
FAMILIES = (HOIST, STAGE, HELPER)
LIMIT = 8
OCCURRENCE = re.compile(rf'\(\s*\(\s*u16\s*\)\s*(?P<call>{IDENT}\s*\([^()]*\))\s*\)')
CALL = re.compile(rf'(?<![\w.>])(?P<name>{IDENT})\s*\(')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}


def _python_statement_start(clean, at, floor):
    """Just after the `;`, `{` or `}` that ends the statement before the one containing `at` (outside parentheses)."""
    depth = 0
    for pos in range(at - 1, floor, -1):
        c = clean[pos]
        if c == ')':
            depth += 1
        elif c == '(':
            depth -= 1
        elif depth <= 0 and c in ';{}':
            return pos + 1
    return floor + 1


_statement_start = _python_statement_start
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _statement_start(clean, at, floor):
        found = _scan.statement_start_before(clean, at, floor)
        return _python_statement_start(clean, at, floor) if found is NotImplemented else found


def _outer_argument(clean, at, skip):
    """(start, end) of the argument of the innermost call (not a name in `skip`) whose parentheses hold `at`."""
    depth = 0
    for pos in range(at - 1, -1, -1):
        c = clean[pos]
        if c == ')':
            depth += 1
        elif c == '(':
            if depth:
                depth -= 1
                continue
            name = re.search(rf'({IDENT})\s*$', clean[:pos])
            if not name or name[1] in skip or name[1] in KEYWORDS:
                continue
            end = close(clean, pos)
            return (pos + 1, end - 1) if end else None
        elif c in ';{}':
            return None
    return None


def _python_top_plus(clean, start, end):
    """The spans of the operands of the depth-0 `+` operators between `start` and `end`."""
    spans, depth, begin = [], 0, start
    for at in range(start, end):
        c = clean[at]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '+' and depth == 0 and clean[at - 1] != '+' and clean[at + 1:at + 2] != '+':
            spans.append((begin, at))
            begin = at + 1
    spans.append((begin, end))
    return spans


_top_plus = _python_top_plus
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_plus(clean, start, end):
        found = _scan.top_plus(clean, start, end)
        return _python_top_plus(clean, start, end) if found is NotImplemented else found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    adders = list(_helpers(clean))
    pure = set(re.findall(rf'\binline\b[^;{{}}]*?\b({IDENT})\s*\(', clean)) | set(adders)
    taken = set(re.findall(IDENT, clean[part.opening:part.end]))
    out, hoists = [], []
    for m in OCCURRENCE.finditer(clean, part.opening, part.end):
        start = _statement_start(clean, m.start(), part.opening)
        at = start
        while at < m.start() and clean[at].isspace():
            at += 1
        statement = clean[at:m.start()]
        if re.search(r'\b(?:else|do)\b', statement) or any(
                (close(clean, at + k.end() - 1) or 0) <= m.start() for k in re.finditer(r'\b(?:if|while|for|switch)\s*\(', statement)):
            continue  # (the call is in a body, not a condition: it must not run unconditionally)
        if any(c['name'] not in pure and c['name'] not in KEYWORDS and (close(clean, at + c.end() - 1) or 0) <= m.start()
               for c in CALL.finditer(statement)):
            continue  # (a real call runs before the one hoisted)
        n = 0
        while f'temp_call{n or ""}' in taken:
            n += 1
        local, offset = f'temp_call{n or ""}', f'temp_sum{n or ""}'
        indent = re.match(r'[ \t]*', source[clean.rfind('\n', 0, at) + 1:]).group(0)
        call = source[m.start('call'):m.end('call')]
        hoist = f'{local} = {call};\n{indent}'
        top = part.opening + 1
        hoists.append((HOIST, edit(source, [(top, top, f'\n  u16 {local};'), (m.start(), m.end(), local), (at, at, hoist)])))
        arg = _outer_argument(clean, m.start(), pure)
        spans = _top_plus(clean, *arg) if arg else []
        holds = [k for k, (a, b) in enumerate(spans) if a <= m.start() and m.end() <= b]
        if len(spans) != 2 or len(holds) != 1:
            continue
        (held_a, held_b), (other_a, other_b) = spans[holds[0]], spans[1 - holds[0]]
        if any(c['name'] not in pure for c in CALL.finditer(clean[other_a:other_b])):
            continue
        held = (source[held_a:m.start()] + local + source[m.end():held_b]).strip()
        addend = source[other_a:other_b].strip()
        stage = f'{offset} = {addend};\n{indent}'
        declare = (top, top, f'\n  u16 {local};\n  s32 {offset};')
        first = (spans[0][0], spans[1][1])
        base = [declare, (at, at, hoist + stage)]
        sums = [(STAGE, f'{held} + {offset}' if holds[0] == 0 else f'{offset} + {held}')]
        if adders:
            sums += [(HELPER, f'{adders[0]}({held}, {offset})'), (HELPER, f'{adders[0]}({offset}, {held})')]
        for family, text in sums:
            out.append((family, edit(source, base + [(first[0], first[1], text)])))
    seen, result = set(), []
    for family, text in out + hoists:
        if text != source and text not in seen:
            seen.add(text)
            result.append((family, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 160}
