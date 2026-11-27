"""One more argument at the end of a callee's calls, when the target's registers hold the caller's parameters there.

A caller hands its own parameters to a callee that m2c saw with one argument:

    jal  f                      guMtxL2F(a);         wrote: guMtxL2F(a, arg1);
     (nothing writes $a1)                                     ($a1 still holds the caller's second parameter)
    ...
    jal  f                      guMtxL2F(b);         wrote: guMtxL2F(b, arg2);
     addu $a1, $s1, $zero                                    ($s1 is `$a2` saved at entry)

`passthrough_argument` passes a caller's parameter only in its own position, so the second call (the third parameter as
the second argument) has no child there, and `target_call_arity` adds trailing constants only. This SN GCC 2.8.1
function was 275 with the second call fixed alone and exact with both.

On the straight-line path from the entry (it ends at the first branch or jump), each `jal`'s argument registers are
followed back to the parameter they hold, through copies into saved registers. A callee gets one child when the C calls
it as often as the target does, every call has the same k arguments (k < 4), every one of its `jal`s is on that path
with `$ak` holding a parameter, at least one of them wrote `$ak` with a copy (a register merely left alone proves
nothing by itself), and the C does not already pass or assign those parameters. A declaration with another number of
parameters (header, matched definition, varargs) rules the callee out; the source's own `f(T)` prototype gains
`s32`. MIPS only. Judged like any child."""
import re

from . import passthrough_argument_repairs as passthrough
from . import target_call_arity_repairs as arity
from .integer_repair_support import calls, edit, split_args, view
from .untouched_argument_parameter import _definition, _header_counts, _param_name, _params

FAMILY = 'forwarded_trailing_argument'
FAMILIES = (FAMILY,)
_ARGUMENTS = ('a0', 'a1', 'a2', 'a3')


def _sites(asm):
    """{callee: [{argument register index: (parameter index, written by a copy)}]} for the `jal`s before any branch."""
    rows = list(arity._instructions(asm))
    registers = {reg: index for index, reg in enumerate(_ARGUMENTS)}
    written = set()
    found = {}

    def step(row):
        op, operands = row
        if not passthrough._transfer(registers, op, operands):
            return False
        dest = re.match(r'\$(\w+)', operands)
        if dest and op not in passthrough._NO_GPR_WRITE:
            written.add(dest[1])
        return True

    pc = 0
    while pc < len(rows):
        op, operands = rows[pc]
        pc += 1
        if op != 'jal':
            if not step(rows[pc - 1]):
                break
            continue
        registers.pop('ra', None)
        if pc == len(rows) or not step(rows[pc]):
            break
        pc += 1
        found.setdefault(operands.strip(), []).append(
            {i: (registers[reg], reg in written) for i, reg in enumerate(_ARGUMENTS) if reg in registers})
        for reg in passthrough._CALLER_SAVED:
            registers.pop(reg, None)
        written.difference_update(passthrough._CALLER_SAVED)
    return found


def variants(source, name, asm, header='', callees=''):
    part = view(source, name)
    if not part or not asm or 'jal' not in asm:
        return []
    head = re.search(rf'\b{re.escape(name)}\s*\((?P<params>[^()]*)\)\s*$', part.clean[:part.opening].rstrip())
    if not head or '...' in head['params']:
        return []
    names = [_param_name(p) for p in _params(head['params'])]
    if not names or None in names:
        return []
    body = part.clean[part.opening:part.end]
    counts = {}
    for callee, _ in arity.calls(asm):
        counts[callee] = counts.get(callee, 0) + 1
    result = []
    for callee, sites in _sites(asm).items():
        if callee == name or not re.fullmatch(r'[A-Za-z_]\w*', callee) or len(sites) != counts.get(callee):
            continue
        found = list(calls(part, callee))
        if len(found) != len(sites):
            continue
        given = [[part.source[start + x:start + y].strip() for x, y in split_args(part.clean[start:end])]
                 if part.clean[start:end].strip() else [] for start, end in found]
        k = len(given[0])
        if k >= 4 or any(len(each) != k for each in given):
            continue
        if not all(k in site and site[k][0] < len(names) for site in sites) or not any(s[k][1] for s in sites):
            continue
        slots = [names[site[k][0]] for site in sites]
        if any(slot in each for slot, each in zip(slots, given)):
            continue
        if any(re.search(rf'(?<![\w.>]){slot}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{slot}\b'
                         rf'|\b{slot}\s*(?:\+\+|--)|&\s*{slot}\b', body) for slot in slots):
            continue
        matched = _definition(callees, callee)
        if matched is not None and len(matched) != k + 1:
            continue
        if _header_counts(header, callee) - {k + 1, None}:
            continue
        edits = []
        declaration = re.search(rf'(?m)^[^\n;{{}}#=]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;',
                                part.clean[:head.start()])
        if declaration and declaration[1].strip():
            params = declaration[1].strip()
            if '...' in params or (params == 'void' and k) or (params != 'void' and len(_params(params)) != k):
                continue
            edits.append((declaration.start(1), declaration.end(1), 's32' if params == 'void' else params + ', s32'))
        for (start, end), each, slot in zip(found, given, slots):
            edits.append((start, end, ', '.join([*each, slot])))
        result.append((FAMILY, edit(source, edits)))
    return result[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header', 'callees'),
          'order': 60, 'archs': ('mips',)}
