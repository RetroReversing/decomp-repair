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

Two more rules, from one N64 function (KMC GCC 2.7.2, 10 -> 100 for the passthrough alone, 10 -> 0 with both):
- m2c reads a constant the game sets up once, before a branch, as an argument of two calls: `go((void *)0x21, 0x80)`
  on one arm and `stop(0x21)` on the other. The passthrough only adds `$a0` to `go`, and the target never sets `$a0`
  for `stop`, so `stop`'s stray argument is a second row to fix. When a callee with one C call and one `jal` that
  the target sets fewer argument registers for than the C passes has, past those, literals equal to a literal the
  passthrough call passes, a second child also drops them (and the parameters the callee's declaration listed past
  the target's count). The passthrough-only child is kept beside it.
- GCC joins the calls both arms of an `if ... else { ... }` make, so the C has two calls where the target has one
  `jal`: the calls of sibling arms count as one site, and all of them get the passthrough.

No child for a varargs callee or caller, a callee whose prototype, header declaration or matched definition
(`callees`) has another number of parameters, a header declaring the caller with other parameters than the child
gives it, a parameter the body assigns, or a call whose arguments already include the parameter. MIPS only. Judged
like any child."""
import re

from . import passthrough_argument_repairs as passthrough
from . import target_call_arity_repairs as arity
from .integer_repair_support import calls, edit, split_args, view
from .pattern_repairs import close
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


def _number(text):
    """The value of an integer literal argument, a pointer cast of one included; None for anything else."""
    cast = _POINTER_LITERAL.fullmatch(text.strip())
    try:
        return int((cast[1] if cast else text).strip(), 0)
    except ValueError:
        return None


def _python_block(clean, at):
    """The `{` that opens the innermost block around `at`, and the `}` that closes it (None, None outside any)."""
    depth = 0
    for i in range(at, -1, -1):
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if not depth:
                end = close(clean, i, '{', '}')
                return i, (end - 1 if end else None)
            depth -= 1
    return None, None


_block = _python_block
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block(clean, at):
        found = _scan.enclosing_open(clean, at + 1, 0, -1)
        if found is not NotImplemented:
            if found < 0:
                return None, None
            end = close(clean, found, '{', '}')
            return found, (end - 1 if end else None)
        return _python_block(clean, at)


def _arm_siblings(clean, first, second):
    """The two calls are in the two arms of one `if ... else { ... }`: GCC joins a call both arms make, so the
    target has one `jal` where the C has two."""
    a_open, a_close = _block(clean, first)
    b_open, _ = _block(clean, second)
    if None in (a_open, a_close, b_open) or a_open == b_open:
        return False
    return re.match(r'\s*else\s*{', clean[a_close + 1:]) is not None and clean[a_close + 1:].find('{') + a_close + 1 == b_open


def _groups(part, callee):
    """The C's calls of `callee` in order, the calls of sibling arms together: [[(start, end), ...], ...]."""
    groups = []
    for start, end in calls(part, callee):
        if groups and _arm_siblings(part.clean, groups[-1][-1][0], start):
            groups[-1].append((start, end))
        else:
            groups.append([(start, end)])
    return groups


def _stray_drops(part, header, callees, per_callee, skip, constants):
    """The calls whose trailing arguments the target never sets up, the same constants as the passthrough's own
    arguments: m2c read one constant set up before a branch as an argument of two calls. [(edits, callee)], one per
    callee that has a single call in the C and a single `jal` in the target."""
    found = []
    for callee, sites in per_callee.items():
        if callee == skip or len(sites) != 1:
            continue
        hits = list(calls(part, callee))
        if len(hits) != 1:
            continue
        start, end = hits[0]
        spans = split_args(part.clean[start:end]) if part.clean[start:end].strip() else []
        count = max((ARGREG.index(r) + 1 for r in sites[0]), default=0)
        if len(spans) <= count:
            continue
        given = [part.source[start + x:start + y].strip() for x, y in spans]
        stray = [_number(text) for text in given[count:]]
        if None in stray or not all(value in constants for value in stray):
            continue
        matched = _definition(callees, callee)
        if matched is not None and len(matched) != count:
            continue
        if _header_counts(header, callee) - {count}:
            continue
        edits = [(start, end, ', '.join(given[:count]))]
        declaration = re.search(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;',
                                part.clean[:part.opening])
        if declaration and declaration[1].strip():
            params = _params(declaration[1])
            if '...' in declaration[1] or len(params) != len(spans):
                continue
            edits.append((declaration.start(1), declaration.end(1), ', '.join(params[:count]) or 'void'))
        found.append((edits, callee))
    return found


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
        found = _groups(part, callee)
        if len(found) != len(sites):
            continue
        for index, regs in enumerate(sites):
            if len(result) >= LIMIT:
                return result
            count = max((ARGREG.index(r) + 1 for r in regs), default=0)
            untouched = [k for k in range(count) if ARGREG[k] not in regs]
            if not untouched:
                continue
            spans = [split_args(part.clean[start:end]) if part.clean[start:end].strip() else []
                     for start, end in found[index]]
            if any(len(each) != count - len(untouched) for each in spans):
                continue
            if not passthrough._entry_arguments_reach(asm, callee, tuple(untouched), site=index):
                continue
            slots = [names[k] if k < len(names) else f'arg{k}' for k in untouched]
            given = [[part.source[start + x:start + y].strip() for x, y in each]
                     for (start, _), each in zip(found[index], spans)]
            if any(slot in text or _assigned(part.clean[part.opening:part.end], slot)
                   for slot in slots for text in given):
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
            constants = {value for each in given for text in each if (value := _number(text)) is not None}
            drops = _stray_drops(part, header, callees, per_callee, callee, constants) if constants else []
            casts = [[_POINTER_LITERAL.fullmatch(text) for text in each] for each in given]
            prefixes = [None]
            if any(any(row) for row in casts):
                prefixes.insert(0, True)
            for uncast in prefixes:
                edits = []
                for (start, end), each, row in zip(found[index], given, casts):
                    arguments = [m[1] if uncast and m else text for m, text in zip(row, each)]
                    filler = iter(arguments)
                    line = ', '.join(slots[untouched.index(k)] if k in untouched else next(filler)
                                     for k in range(count))
                    edits.append((start, end, line))
                if added:
                    edits.append((head.start('params'), head.end('params'), ', '.join(params + added)))
                text = edit(part.source, edits)
                if text != source and (FAMILY, text) not in result:
                    result.append((FAMILY, text))
                # (the target's one constant, set up before the branch, was drafted as an argument of the next
                # call as well: the passthrough alone leaves that call's stray `$a0` setup, 100 against 10, and
                # only with the call's argument gone is the child exact)
                for more, _ in drops:
                    both = edit(part.source, edits + more)
                    if both != source and (FAMILY, both) not in result:
                        result.append((FAMILY, both))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header', 'callees'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py); `callees` from the caller
