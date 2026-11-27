"""One integer literal passed to several calls, held in a local set early, however it is masked.

    obj->a = build(p, &t, 0x64, 0x64, 0, 1, 0xFF, 0xFF, 0xFF, 0xFF, 0x40 & 0xFF);
    obj->b = build(p, &t, 0x78, 0x78, 0, 1, 0xFF, 0xFF, 0xFF, 0xFF, 0x40 & 0xFF);
->  k = 0x40;   (before the first store of the run)
    obj->a = build(..., k & 0xFF);   obj->b = build(..., k & 0xFF);

m2c writes a one-byte stack argument as `0x40 & 0xFF` at each call. The game had it in a variable (`alpha = 0x40`)
set before the stores that start the function's build-up and read at both calls, so it lives in a saved register across
both calls and the load is one insn the scheduler puts with the first stores. A N64 effect constructor (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O1 -g`, 124 instructions) stood at 505 with the literal at each call (726 once the draft's
scaffolding was gone) and was exact (0) with `temp_s2 = 0x40;` set after the header stores and `temp_s2 & 0xFF` at
both calls. `integer_argument_early_local` holds one literal at one call and only a bare one, and walks back three
statements; this one is for a literal the calls repeat, masked or not, with the set walked back as far as the block
goes (a dozen statements), since the target's order decides.

Children, one local and one place each: a literal (not 0 or 1) in the fifth or a later argument of two or more calls in
the function, bare or `K & MASK`, and used once per call; every spelling becomes the local (`k_<literal>`, kept with its mask) and the local is
set on the line before the first call's statement or before one of the plain statements above it in the same block (never
across a brace, an `if`/loop or a declaration). The local is declared `s32` after the leading declarations. Gate: when
the target's assembly is given, the literal must be loaded by an immediate in it. Nothing is offered for a function with
`volatile`, `asm` or a preprocessor line. Proposals only; the compiler and the byte judge decide."""
import re

from .constant_in_local import _CALL_ARGUMENT, _INT, _NOT_STATEMENT, _STATEMENT, _int, _name
from .integer_argument_early_local import _declaration, _loaded
from .integer_repair_support import IDENT, edit, view
from .store_run_order import _insert_declaration

FAMILY = 'repeated_stack_literal_local'
FAMILIES = (FAMILY,)
LIMIT = 16
BACK = 12
_ARGUMENT = re.compile(rf'(?:^|,)\s*(?P<k>{_INT})(?=\s*(?:&\s*(?:{_INT})\s*)?(?:,|$))')


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body[part.opening:part.end], re.M):
        return []
    used = set(re.findall(IDENT, body[part.opening:part.end]))
    statements = [hit for hit in _STATEMENT.finditer(body, part.opening + 1, part.end)
                  if body[:hit.start(1)].rstrip()[-1:] in ('', ';', '{', '}')]
    sites = {}
    for index, hit in enumerate(statements):
        text = hit[2]
        first = re.match(r'\s*(\w+)', text)
        if not first or first[1] in _NOT_STATEMENT or _declaration(text):
            continue
        for call in _CALL_ARGUMENT.finditer(text):
            callee = call['callee']
            if callee in _NOT_STATEMENT or callee == 'sizeof' or callee.startswith('M2C_') or callee.isupper():
                continue
            for argument in _ARGUMENT.finditer(call['args']):
                literal = argument['k']
                if _int(literal) in (0, 1) or call['args'][:argument.start('k')].count(',') < 4:
                    continue
                sites.setdefault(_int(literal), []).append((index, hit.start(2) + call.start('args') + argument.start('k'), literal))
    out = []
    for value, found in sites.items():
        statements_with = [index for index, _, _ in found]
        # a literal one call repeats (four 0xFF) already shares one register: the repeat that matters is across calls
        if len(set(statements_with)) < 2 or len(statements_with) != len(set(statements_with)) or not _loaded(asm, value):
            continue
        local = _name('k', found[0][2])
        if local in used:
            continue
        first = min(index for index, _, _ in found)
        spots = [first]
        for back in range(first - 1, max(first - BACK, 0) - 1, -1):
            earlier = statements[back]
            between = body[earlier.end():statements[back + 1].start(1)]
            lead = re.match(r'\s*(\w+)', earlier[2])
            if '{' in between or '}' in between or not lead or lead[1] in _NOT_STATEMENT or _declaration(earlier[2]):
                break
            spots.append(back)
        for spot in spots:
            target = statements[spot]
            edits = [(at, at + len(literal), local) for _, at, literal in found]
            edits.append((target.start(2), target.start(2), f'{local} = {found[0][2]};\n{target[1]}'))
            child = edit(source, edits)
            moved = view(child, name)
            if moved:
                out.append((FAMILY, _insert_declaration(child, moved, f's32 {local};')))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
