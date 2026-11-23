"""A call's address argument computed before the `if` that sets the call's last argument, not after it.

`var = 1; if (!(a > b)) { var = 0; } call(p + 0x24, 1, var);` leaves the call's address argument to the join: m2c's
order puts the `addiu $a0,p,0x24` after the branch, and the delay-slot filler then turns the one-insn `if` into a
branch-likely over `move $a2,$zero` (`bc1fl L; move $a2,$zero`). With the address staged in a local before the `if`
(`arg = p + 0x24;`) it is the last insn above the branch, fills its slot, and the branch is the plain one the target
has (`bc1t L; addiu $a0,$s1,0x24; move $a2,$zero; L: jal`): 750 -> 230 in a 970-instruction N64 state-machine handler
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) with two such arms staged. Hypothesis, not read in the compiler source:
the order of the filler candidates in reorg.

`variants` takes a call statement whose first argument is `name + constant` for a pointer `name` (a parameter or local
of a pointer type) and that directly follows a one-statement `if (...) { local = ...; }`, assigns the address to a new
local of the pointer's type just before that `if`, and passes it. One child per such call, one with all of them, at
most 4. A candidate rewrite: the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines

FAMILY = 'call_arg_stage_before_guard'
FAMILIES = (FAMILY,)
LIMIT = 4
CALL = re.compile(r'(?P<callee>[A-Za-z_]\w*)\s*\(\s*(?P<base>[A-Za-z_]\w*)\s*\+\s*(?P<off>0[xX][0-9A-Fa-f]+|\d+)\s*(?P<rest>[,)].*)\)\s*;')
ASSIGN = re.compile(r'[A-Za-z_]\w*\s*=(?!=)[^;]*;')


def _pointer_type(source, part, name):
    """The declared type text of a pointer parameter or local called `name`, as written (`void *`), or None."""
    head = source[:part.opening]
    declared = re.findall(rf'([A-Za-z_][\w\s]*?\s*\*+)\s*{re.escape(name)}\b\s*[,;)=]', source[part.opening - 400 if part.opening > 400 else 0:part.end])
    if declared:
        return ' '.join(declared[-1].split()).replace(' *', ' *')
    match = re.search(rf'([A-Za-z_][\w\s]*?\s*\*+)\s*{re.escape(name)}\b', head[head.rfind('\n') + 1:])
    return ' '.join(match[1].split()) if match else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    edits = []
    for index, line in enumerate(body):
        call = CALL.fullmatch(line.stripped)
        if not call or index < 4:
            continue
        close = index - 1
        if body[close].stripped != '}':
            continue
        # the `if (...)` whose block closes on the line before the call, holding one assignment
        opening = next((i for i in range(close - 1, max(close - 6, -1), -1) if body[i].stripped == '{' and block_end(body, i) == close), None)
        if opening is None or opening < 1 or not re.match(r'if\s*\(', body[opening - 1].stripped):
            continue
        inside = [item for item in body[opening + 1:close] if item.stripped]
        if len(inside) != 1 or not ASSIGN.fullmatch(inside[0].stripped):
            continue
        kind = _pointer_type(source, part, call['base'])
        if not kind:
            continue
        local = f"{call['base']}_arg"
        if re.search(rf'\b{local}\b', part.clean):
            continue
        guard = body[opening - 1]
        stage = f"{guard.indent}{local} = {call['base']} + {call['off']};\n"
        call_text = line.source.replace(f"{call['base']} + {call['off']}", local, 1)
        edits.append((guard.start, line.end, stage + ''.join(item.source + '\n' for item in body[opening - 1:close + 1])
                      + call_text + '\n', kind, local))
    out = []
    for first, last, text, kind, local in edits[:LIMIT]:
        child = apply(source, [(first, last, text)])
        out.append(_declare(child, name, f'{kind}{local};' if kind.endswith('*') else f'{kind} {local};'))
    if len(edits) > 1:
        child = apply(source, [(a, b, t) for a, b, t, _, _ in edits])
        for kind, local in dict.fromkeys((kind, local) for _, _, _, kind, local in edits):
            child = _declare(child, name, f'{kind}{local};' if kind.endswith('*') else f'{kind} {local};')
        out.append(child)
    return [(FAMILY, child) for child in dict.fromkeys(out)][:LIMIT]


def _declare(source, name, declaration):
    part = view(source, name)
    first = re.search(r'\n', source[part.opening:])
    at = part.opening + first.end()
    indent = re.match(r'[ \t]*', source[at:])[0] or '    '
    return source[:at] + f'{indent}{declaration}\n' + source[at:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
