"""A `void` function whose target hands back a LOCAL pointer in `$v0`: declare it to return that local.

    void f(void *arg0) { temp_v0 = alloc(...); init(temp_v0); ...; temp_v0->x = arg0->x; }
    void *f(void *arg0) { ...; temp_v0->x = arg0->x; return temp_v0; }

A function that allocates (or is handed) an object, fills it in and ends with a store through it is compiled by KMC GCC
2.7.2 (N64, `-O2`) with the object kept in a saved register (`move $s0, $v0` after the allocator's call) and, in front
of the last store, `move $v0, $s0`: the store is addressed through `$v0` because the function RETURNS the object. m2c
cannot see that, no caller reads `$v0`, so its draft is `void` and the last store goes through `$s0`: one row short (the
`move`) plus the two register rows that follow (110 -> 0 on two small N64 functions, 44 and 62 instructions, with only
the return type and a `return temp_v0;` added as the last statement). Copying the local into a second local before the
last store does not add the `move` (four spellings, all 110).

`void_parameter_return` covers `$v0` copied from an incoming PARAMETER register; `returned_register_local` returns a
local only when the draft already returns a value, because a changed return type needs evidence. This is the evidence
for a local: the target's last write to `$v0` before its `jr $ra` is a plain copy (`returned_register`) of a saved or
temporary register that the function filled with a call's result (`move $sN, $v0` after a `jal`) or with a parameter
copied in the prologue, and the C has a local pointer that fits: the local m2c named after that register
(`temp_s0`/`var_s0`) first, then the pointer locals assigned from a call, the one stored through the most and assigned
last first. One child each (they differ only in the declared type, which the target's bytes cannot tell apart):
- the local's own pointer type with `return local;` (the usual value);
- `s32` with `return (s32) local;`.
Every bare `return;` becomes the same return and a final one is added when the body does not end in one, so the return
sits after the last store. A bare `return;` that can run BEFORE the local is assigned (an early exit that leaves `$v0`
as the last call set it: `if (f() == 0x30) { g(a); return; }`) stays as it is, the way the matched twin of such a function
was written (130 -> 0 on a 25-instruction N64 constructor; before, no child was offered at all). Nothing is offered when the
function is not `void`, the project's header declares the function `void`, the register is an argument register (that is
`void_parameter_return`), or the local is assigned more than the evidence allows (an array, a non-pointer). Hypothesis,
not confirmed in the compiler source: the copy comes from the front end's return expression being the one value live
across the final stores. Each child is judged; a caller that ignores the value compiles the same.

The same children are also built on the function with its `do { } while (0)` fences opened (`void_returned_local_unfenced`,
`scaffold_strip.unfence`). A long search keeps the copy at the end of the function with fences between the last
statements; the return alone then scores WORSE (225 -> 325 on a 54-instruction N64 constructor whose fences kept the
stores apart), because the scheduler may not move the `move $v0, $s0` across a fence, and opened it is 0. The
unfenced child is only offered for a function that has fences, so a saved best that carries its search's scaffolding
reaches the return in one step."""
import re

from . import mips_regions as flow
from . import scaffold_strip
from .integer_repair_support import IDENT, edit, split_args, view
from .returned_register_local import _copied_parameter, _instructions, _variables, returned_register

FAMILY = 'void_returned_local'
UNFENCED = 'void_returned_local_unfenced'
FAMILIES = (FAMILY, UNFENCED)

LIMIT = 2


def _holds_call_result(asm, register):
    """Whether the target copies a call's result (`$v0`) into `register` after some `jal`."""
    called = False
    for op, args in _instructions(asm):
        if op in flow.CALLS:
            called = True
        elif called and op in ('move', 'addu', 'or', 'daddu') and re.match(rf'\${register}\s*,\s*\$v0\b', args):
            return True
    return False


def _ends_in_return(body):
    tail = body.rstrip()[1:-1].rstrip()
    last = re.search(r'\breturn\b[^;{}]*;$', tail)
    if not last:
        return False
    before = tail[:last.start()].rstrip()
    return before.count('{') - before.count('}') == 0 and before[-1:] in ('', ';', '{', '}')


def _assignments(body, local):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)\s*(?P<rhs>[^;]*);', body)]


def _stored_through(body, local):
    return len(re.findall(rf'\(\s*{re.escape(local)}\s*,[^;=]*\)\s*=(?!=)|(?<![\w.>]){re.escape(local)}\s*->[^;=]*=(?!=)'
                          rf'|\*\s*\(?\s*{re.escape(local)}\b[^;=]*=(?!=)', body))


def _candidates(part, params, register, asm):
    variables = _variables(part, params)
    body = part.clean[part.opening:part.end]
    copied = _copied_parameter(asm, register)
    call_result = _holds_call_result(asm, register)
    ranked = []
    for local, (kind, index) in variables.items():
        if '[' in kind or '*' not in kind:
            continue
        found = _assignments(body, local)
        if index is not None:
            if index == copied:
                ranked.append((1, 0, 0, local, kind))
            continue
        if not found:
            continue
        named = re.fullmatch(rf'\w+_{register}', local) is not None
        from_call = any(re.match(r'\s*(?:\([^()]*\)\s*)?' + IDENT + r'\s*\(', m['rhs']) for m in found)
        if named or (call_result and from_call):
            ranked.append((0 if named else 2, -_stored_through(body, local), -found[-1].start(), local, kind))
    return [(local, kind, _first_assignment(body, local)) for _, _, _, local, kind in sorted(ranked)[:LIMIT]]


def _first_assignment(body, local):
    found = _assignments(body, local)
    return found[0].start() if found else 0


def variants(source, name, asm, header=''):
    out = _returning(source, name, asm, header, FAMILY)
    opened = scaffold_strip.unfence(source, name)
    if opened:
        seen = {text for _, text in out}
        out += [(family, text) for family, text in _returning(opened, name, asm, header, UNFENCED)
                if text not in seen]
    return out


def _returning(source, name, asm, header, family):
    register = returned_register(asm)
    if not register or re.fullmatch(r'a[0-3]', register):
        return []
    part = view(source, name)
    if not part:
        return []
    head = re.search(rf'(?P<result>[^;{{}}]*?)\b{re.escape(name)}\s*\((?P<params>[^()]*)\)\s*$',
                     part.clean[:part.opening].rstrip())
    void = re.search(r'\bvoid\s*$', head['result']) if head else None
    if not void or not re.fullmatch(r'\s*(?:(?:static|inline|extern)\s+)*', head['result'][:void.start()].rsplit('\n', 1)[-1]):
        return []
    if re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', header or ''):
        return []
    text_params = head['params'].strip()
    params = [] if text_params in ('', 'void') else [text_params[a:b] for a, b in split_args(text_params)]
    body = part.clean[part.opening:part.end]
    bare = list(re.finditer(r'\breturn\s*;', body))
    result_at = head.start('result') + void.start()
    protos = list(re.finditer(rf'(?m)^[ \t]*(?:extern[ \t]+)?void(?=\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*;)',
                              part.clean[:part.opening]))
    result = []
    for local, kind, first in _candidates(part, params, register, asm):
        # a bare return that can run before the local holds the object is an early exit: it keeps leaving `$v0` as it is
        early = [m for m in bare if m.start() < first] if _assignments(body, local) else []
        late = [m for m in bare if m not in early]
        forms = [(kind, local), ('s32', f'(s32) {local}')]
        for new_type, value in forms:
            edits = [(result_at, result_at + 4, new_type)]
            edits += [(m.end() - 4, m.end(), new_type) for m in protos]
            edits += [(part.opening + m.start(), part.opening + m.end(), f'return {value};') for m in late]
            if not _ends_in_return(body) or (early and bare[-1] in early):
                close = part.opening + len(body.rstrip()) - 1
                lead = '' if part.clean[close - 1] == '\n' else '\n'
                edits.append((close, close, f'{lead}    return {value};\n'))
            text = edit(source, edits)
            if text != source:
                result.append((family, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 62, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
