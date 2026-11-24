"""An argument register the target leaves alone before one call of several: the caller's own parameter, passed on there.

A function that tests a field and, on its early-return arm, calls a two-argument callee after setting only `$a1`

    lw   $v0, 0x7C($s1)              (the arm is reached through branches that never write $a0)
    beqz $v0, L
    ...
    jal  f
    addiu $a1, $zero, 1              (the delay slot sets the second argument; $a0 is still the caller's own)

is drafted by m2c with the one argument it saw set up, written for the wrong slot and cast to the type the callee's
first parameter seemed to have: `f((void *)1);` where the game wrote `f(arg0, 1);` (the callee's other call in the
same function, `f(arg0, 1)`, was already drafted right: its `$a0` is written there). One register row differed
(`addiu $a0, $zero, 1` against `addiu $a1, $zero, 1`, score 5 on a 62-instruction N64 function, KMC GCC 2.7.2);
the child below is exact.

`untouched_argument_parameter` does this for a callee called once on the straight-line path from the entry and for a
slot between written ones; `passthrough_argument` does it for a caller's parameter it already has, at one call, on that
same straight-line path. A branch before the call ends their proof, and so does a second call of the callee. This
family proves each call of the callee on its own, over every route from the entry (`passthrough_argument.
_entry_arguments_reach` with `site`): the callee's n-th `jal` is paired, in order, with the C's n-th call of it when
the C makes as many calls as the target does, the target writes some of `$a0`-`$a3` before that `jal` and leaves
lower ones untouched, those registers still hold the caller's own values on every route, and the C passes exactly as
many arguments as the target writes. The child passes the caller's `argK` at each untouched slot (the caller's
signature gains `s32 argK` and the parameters before it when it lacked them), the C's own arguments filling the
written slots in order. An argument that is a pointer cast of an integer literal (`(void *)1`, m2c's guess for the
slot it was written for) is offered without the cast, then as it was.

No child for a varargs callee or caller, a callee whose prototype, header declaration or matched definition
(`callees`) has another number of parameters, a header declaring the caller with other parameters than the child
gives it, a parameter the body assigns, or a call whose arguments already include the parameter. MIPS only. Judged
like any child."""
import re

from . import passthrough_argument_repairs as passthrough
from . import target_call_arity_repairs as arity
from .integer_repair_support import calls, edit, split_args, view
from .untouched_argument_parameter import (
    ARGREG,
    _definition,
    _header_counts,
    _param_name,
    _params,
)

FAMILY = 'untouched_slot_passthrough'
FAMILIES = (FAMILY,)
LIMIT = 6
_POINTER_LITERAL = re.compile(r'\(\s*[A-Za-z_][\w ]*\*+\s*\)\s*(-?(?:0[xX][0-9A-Fa-f]+|\d+))')


def _assigned(body, name):
    return bool(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b'
                          rf'|\b{re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', body))


def variants(source, name, asm, header='', callees=''):
    part = view(source, name)
    if not part or not asm:
        return []
    head = re.search(rf'\b{re.escape(name)}\s*\((?P<params>[^()]*)\)\s*$', part.clean[:part.opening].rstrip())
    if not head or '...' in head['params']:
        return []
    params = _params(head['params'])
    names = [_param_name(p) for p in params]
    if None in names:
        return []
    sequence = arity.calls(asm)
    per_callee = {}
    for callee, regs in sequence:
        per_callee.setdefault(callee, []).append(regs)
    result = []
    for callee, sites in per_callee.items():
        if callee == name:
            continue
        found = list(calls(part, callee))
        if len(found) != len(sites):
            continue
        for index, regs in enumerate(sites):
            if len(result) >= LIMIT:
                return result
            count = max((ARGREG.index(r) + 1 for r in regs), default=0)
            untouched = [k for k in range(count) if ARGREG[k] not in regs]
            if not untouched:
                continue
            start, end = found[index]
            spans = split_args(part.clean[start:end]) if part.clean[start:end].strip() else []
            if len(spans) != count - len(untouched):
                continue
            if not passthrough._entry_arguments_reach(asm, callee, tuple(untouched), site=index):
                continue
            slots = [names[k] if k < len(names) else f'arg{k}' for k in untouched]
            given = [part.source[start + x:start + y].strip() for x, y in spans]
            if any(slot in given or _assigned(part.clean[part.opening:part.end], slot) for slot in slots):
                continue
            matched = _definition(callees, callee)
            if matched is not None and len(matched) != count:
                continue
            if _header_counts(header, callee) - {count}:
                continue
            added = [f's32 arg{k}' for k in range(len(names), max(untouched) + 1)]
            own = _header_counts(header, name)
            if added and own and own != {len(params) + len(added)}:
                continue
            declaration = re.search(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;',
                                    part.clean[:head.start()])
            if declaration:
                if '...' in declaration[1]:
                    continue
                if declaration[1].strip() and declaration[1].strip() != 'void':
                    if len(_params(declaration[1])) != count:
                        continue
            prefixes = [given]
            casts = [_POINTER_LITERAL.fullmatch(text) for text in given]
            if any(casts):
                prefixes.insert(0, [m[1] if m else text for m, text in zip(casts, given)])
            for arguments in prefixes:
                filler = iter(arguments)
                line = ', '.join(slots[untouched.index(k)] if k in untouched else next(filler)
                                 for k in range(count))
                edits = [(start, end, line)]
                if added:
                    edits.append((head.start('params'), head.end('params'), ', '.join(params + added)))
                text = edit(part.source, edits)
                if text != source and (FAMILY, text) not in result:
                    result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header', 'callees'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py); `callees` from the caller
