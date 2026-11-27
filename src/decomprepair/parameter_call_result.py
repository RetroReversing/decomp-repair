"""A call's result written back into the parameter it was computed from, as the game reused it.

m2c gives every value its own local, so `x = absS32(x);` comes back as

    s32 f(s32 arg0, s32 arg1) {
        s32 var_s0;
        var_s0 = absS32(arg0);          ->    arg0 = absS32(arg0);

and every later read names the local. The parameter and the local are then two pseudo registers where the game had
one. On a 39-instruction N64 vector length (SN64 GCC 2.8.1, `-G0 -mips3 -mgp32 -mfp32 -O2`) with both coordinates in
locals the app's judge gave 75 (the two saved registers swapped and the second value left in `$a0`); both written back
into the parameters, with the products shifted in place (`shifted_operand_locals`), was exact. `param_in_place_update`
is the same reuse for `temp = param OP expr;`, and `parameter_copy_drop` for a plain copy; neither reads a call.

Offered where a statement `local = callee(..., param, ...);` is the parameter's last mention, the local has the
parameter's integer type and is not mentioned before it, and the statement is outside any loop: each such pair alone,
and all of them in one child. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import INTEGER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'parameter_call_result'
FAMILIES = (FAMILY,)
LIMIT = 6

_CALL = re.compile(r'(?m)^[ \t]*(?P<local>[A-Za-z_]\w*)\s*=\s*(?P<callee>[A-Za-z_]\w*)\s*\((?P<args>[^;{}]*)\)\s*;')
_LOOP = re.compile(r'\b(?:for|while|do)\b')


def _in_loop(body, at):
    """Whether `at` is inside a loop, or the function has a backward jump that could make it one."""
    if re.search(r'\bgoto\b', body):
        return True
    for loop in _LOOP.finditer(body, 0, at):
        opening = body.find('{', loop.end())
        end = close(body, opening, '{', '}') if opening >= 0 else None
        if end is None or end > at:
            return True
    return False


def _pairs(part):
    """[(declaration span, parameter, local, call match)] of the calls whose result can take the parameter's name."""
    head = part.clean[part.clean.rfind('(', 0, part.opening):part.opening]
    parameters = {hit['name']: ' '.join(hit['type'].split()) for hit in
                  re.finditer(rf'\b(?P<type>{INTEGER})\s+(?P<name>[A-Za-z_]\w*)\s*(?=[,)])', head)}
    body, found, used = part.body, [], set()
    for call in _CALL.finditer(body):
        local = call['local']
        declared = re.search(rf'(?m)^[ \t]*(?P<type>{INTEGER})\s+{local}\s*;[ \t]*\n', body)
        if not declared or local in used or local in parameters:
            continue
        mentions = [hit.start() for hit in re.finditer(rf'\b{local}\b', body)]
        if len([at for at in mentions if at < call.start()]) != 1 or _address_taken(body, local):
            continue
        if re.search(rf'\b{local}\b', call['args']) or _in_loop(body, call.start()):
            continue
        for argument in re.findall(r'[A-Za-z_]\w*', call['args']):
            if (parameters.get(argument) == ' '.join(declared['type'].split()) and argument not in used
                    and not re.search(rf'\b{argument}\b', body[call.end():]) and not _address_taken(body, argument)):
                found.append((declared.span(), argument, local, call))
                used |= {argument, local}
                break
    return found[:LIMIT]


def _apply(part, chosen):
    base, edits = part.opening + 1, []
    for (start, end), parameter, local, call in chosen:
        edits.append((base + start, base + end, ''))
        for hit in re.finditer(rf'(?<![.>])\b{local}\b', part.body):
            if not start <= hit.start() < end:
                edits.append((base + hit.start(), base + hit.end(), parameter))
    return edit(part.source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    pairs = _pairs(part)
    out = [(FAMILY, _apply(part, pairs))] if len(pairs) > 1 else []
    return out + [(FAMILY, _apply(part, [pair])) for pair in pairs]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
