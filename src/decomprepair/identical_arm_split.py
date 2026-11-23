"""An identical-arm guard cut into runs, each its own guard, with the tail written once after them.

`if (c) { A; B; C; D } else { A; B; C; D }` is the program `A; B; C; D`, but not the same RTL: each arm is a basic
block of its own, so the first scheduler (`sched.c`) schedules its statements together, and the two arms are merged
only later, by cross-jumping after allocation. Two consecutive guards `if (c) { A; B } else { A; B }  if (c) { C }
else { C }` put the runs in blocks of their own: the scheduler cannot move a load of the second run above a store of the
first (nor the reverse), and a statement written outside the guards (`D`) is in the join's block, where its own
register preferences apply. gcc 2.7.2 (KMC, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, a 235-instruction N64 menu
function, 390 -> 0): three byte stores of zero, two word copies between globals and a counter reset sat in both arms of
one guard, and the scheduler hoisted the copies' loads above the stores (and the loop bound's load above the copies);
the target keeps the stores first, the loads next and the bound's load after them. Written as one guard of the three
stores, one of the two copies and the counter reset after both, it matched. Each step is only worth it together with the
others, so the family offers the combinations as single children.

The guard is only rewritten when it is an identical-arm guard of plain statements (no braces inside) and its condition
has no call, assignment or increment: then every guard is the program of its arm, however the runs are cut, whatever the
earlier runs write.  A candidate for the exact judge, never a verdict. (The compiler explanation is a hypothesis from
reading `sched.c`'s basic-block scheduling, confirmed only by the judge's result on that function.)
"""
import re

from .integer_repair_support import edit, view

FAMILIES = ('identical_arm_split',)
LIMIT = 24
ARMS = re.compile(r'(?P<head>\bif\s*\((?P<cond>[^;{}]*)\)\s*)\{(?P<a>[^{}]*)\}\s*else\s*\{(?P<b>[^{}]*)\}')
IMPURE = re.compile(r'[A-Za-z_]\w*\s*\(|(?<![=!<>])=(?!=)|\+\+|--')


def _statements(text):
    """The arm's statements, each with its `;`, or None when a statement is not plain."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ';' and depth == 0:
            out.append(' '.join(text[start:i + 1].split()))
            start = i + 1
    if text[start:].strip() or depth or not out:
        return None
    return out


def _guard(head, cond, run, indent):
    body = ('\n' + indent + '    ').join(run)
    arm = '{\n' + indent + '    ' + body + '\n' + indent + '  }'
    return f'if ({cond.strip()})\n{indent}  {arm}\n{indent}else\n{indent}  {arm}'


def _written(cond, stmts, cuts, hoist, indent):
    """Runs cut after the statement counts in `cuts`, the last `hoist` statements written after the guards."""
    kept = stmts[:len(stmts) - hoist]
    bounds = [0, *cuts, len(kept)]
    runs = [kept[a:b] for a, b in zip(bounds, bounds[1:]) if a < b]
    pieces = [_guard('', cond, run, indent) for run in runs] + list(stmts[len(kept):])
    return ('\n' + indent).join(pieces)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for m in ARMS.finditer(part.clean, part.opening, part.end):
        cond = m['cond']
        if IMPURE.search(re.sub(r'\(\s*(?:u|s)(?:8|16|32)\s*\)\s*', '', cond)):
            continue
        a, b = _statements(m['a']), _statements(m['b'])
        if not a or a != b or len(a) < 2:
            continue
        line = part.clean[part.clean.rfind('\n', 0, m.start()) + 1:m.start()]
        if line.strip():
            continue  # the guard shares its line with another statement or an `else`: leave it to the other families
        indent = re.match(r'[ \t]*', line)[0]
        n = len(a)
        plans = []
        for hoist in range(0, min(3, n - 1)):
            kept = n - hoist
            for k in range(1, kept):
                plans.append(((k,), hoist))
            if kept > 2:
                plans.append((tuple(range(1, kept)), hoist))  # every statement its own guard
        for hoist in range(1, min(3, n - 1) + 1):
            plans.append(((), hoist))  # only the tail written after the one guard
        for cuts, hoist in dict.fromkeys(plans):
            if hoist == n:
                continue
            text = _written(cond, a, cuts, hoist, indent)
            out.append(edit(source, [(m.start(), m.end(), text)]))
    return [(FAMILIES[0], c) for c in dict.fromkeys(out) if c != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
