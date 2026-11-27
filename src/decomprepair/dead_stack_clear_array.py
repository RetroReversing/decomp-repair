"""A run of `sh $zero, N($sp)` stores the target interleaves with its other stores: a local array the original zeroed.

A draft sized the frame with a scaffold (`volatile unsigned char pad;`, often inside an `if (1)` block) and the target
still has stores into that space, written between the stores of a structure the function fills:

    sh   $zero, 0x20($sp)     sw $zero, 0xC4($v0)
    sh   $zero, 0x22($sp)     sw $zero, 0xC8($v0)       (the stores alternate, one stack store before each)

No volatile byte makes those, and writing them together or after the others orders them wrongly. The original had a local
array it cleared an element at a time (`s16 sp[3]; ... sp[0] = 0; *(s32 *)(p + 0xC4) = 0; sp[1] = 0; ...`): KMC GCC 2.7.2
`-O1` keeps the stores because the array is a stack object the function writes (300 -> 60 with the array interleaved, then
the existing `temporary_hoist` took it to 0 on an N64 function that cleared a three-element halfword array between word
stores of a record). Where the array sits in the frame comes out of its declaration, so the rewrite replaces the scaffold's
declaration with the array.

Read from the target's assembly: after the last call (the outgoing-argument stores before it are not locals), a run of at
least two stores of `$zero` to consecutive stack slots of one width (`sb`, `sh`, `sw`) is an array of `s8`, `s16` or `s32`.
Each stack store is placed before the C statement that makes the next store through a pointer or a global in the
target's order (a statement `*(T *)(...) = v;`, `p->f = v;`, `p[i] = v;`, or an assignment to an `extern` global; the n-th
store in the assembly is the n-th such statement in the source).

dead_stack_clear_array
    The scaffold `volatile T pad;` (a scalar local nothing else reads) replaced by `S sp[N];` (or `S sp[N];` after the leading
    declarations when there is none) and `sp[k] = 0;` before the statements the assembly puts them before.
dead_stack_clear_block
    The same array with every element cleared before the first of those statements.

A candidate for the exact judge; a function with `asm`, or whose own name `sp` is taken, gets none.
"""
import re

from .frame_padding_repairs import declaration_ends
from .integer_repair_support import IDENT, edit, view

FAMILY = 'dead_stack_clear_array'
BLOCK_FAMILY = 'dead_stack_clear_block'
FAMILIES = (FAMILY, BLOCK_FAMILY)
LIMIT = 16  # elements: a longer run is a buffer, not a cleared array
WIDTHS = {'sb': (1, 's8'), 'sh': (2, 's16'), 'sw': (4, 's32')}

_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_INSN = re.compile(r'^(?:/\*.*?\*/\s*)?(?P<op>[a-z][a-z0-9.]*)\s+(?P<args>[^#\n]*?)\s*$')
_STORE = re.compile(rf'^\$(?P<src>\w+)\s*,\s*(?P<off>-?{_NUMBER}|%lo\([^)]*\))\(\$(?P<base>\w+)\)$')
_STORE_OPS = {'sb', 'sh', 'sw', 'sd', 'swc1', 'sdc1', 'swl', 'swr', 'sdl', 'sdr', 'swc2', 'sdc2'}
_SCAFFOLD = re.compile(r'(?m)^(?P<indent>[ \t]*)volatile\s+(?:unsigned\s+)?(?:char|short|int|u8|s8|u16|s16|u32|s32)\s+'
                       rf'(?P<name>{IDENT})\s*;[ \t]*\n')
_STATEMENT = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>\*[^=;\n]*|{IDENT}(?:\s*(?:\[[^\]\n]*\]|->\s*{IDENT}|\.\s*{IDENT}))+|{IDENT})'
                        r'\s*=(?!=)[^;\n]*;[ \t]*$')


def clears(asm):
    """(op, [(offset, index of the next store through a pointer or global)]) for the run of zero stores to the stack
    after the last call, or None."""
    stores, last_call = [], -1
    for text in asm.splitlines():
        hit = _INSN.match(text.strip())
        if not hit:
            continue
        op, args = hit['op'], hit['args']
        if op in ('jal', 'jalr'):
            last_call = len(stores)
        if op not in _STORE_OPS:
            continue
        found = _STORE.match(args)
        if found:
            stores.append((op, found['src'], 0 if found['off'].startswith('%') else int(found['off'], 0), found['base']))
    seen, run = 0, []
    numbered = []
    for op, src, off, base in stores:
        if base == 'sp':
            numbered.append((op, src, off, None))
        else:
            numbered.append((op, src, off, seen))
            seen += 1
    # the stores after the last call; each stack store is placed before the next one through another base
    tail = numbered[last_call + 1:] if last_call >= 0 else numbered
    for position, (op, src, off, order) in enumerate(tail):
        if order is not None or op not in WIDTHS or src != 'zero':
            continue
        following = next((o for _, _, _, o in tail[position + 1:] if o is not None), None)
        run.append((op, off, following))
    if len(run) < 2 or len({op for op, _, _ in run}) != 1:
        return None
    op = run[0][0]
    step = WIDTHS[op][0]
    offsets = sorted(off for _, off, _ in run)
    if len(run) > LIMIT or any(b - a != step for a, b in zip(offsets, offsets[1:])):
        return None
    return op, run


def variants(source, name, asm=''):
    part = view(source, name)
    found = clears(asm or '') if part else None
    if not found or re.search(r'\b(?:asm|__asm__)\b', part.clean):
        return []
    op, run = found
    run = sorted(run, key=lambda row: row[1])
    kind = WIDTHS[op][1]
    array = 'sp'
    if re.search(rf'\b{array}\b', part.clean[part.opening:part.end]):
        return []
    body_start = part.opening + 1
    names = _globals(source)
    statements = [m for m in _STATEMENT.finditer(part.clean, body_start, part.end)
                  if re.search(r'[*\[\].>]', m['lhs']) or m['lhs'].strip() in names]
    scaffold = next((m for m in _SCAFFOLD.finditer(part.clean, body_start, part.end)
                     if len(re.findall(rf'\b{m["name"]}\b', part.clean[body_start:part.end])) == 1), None)
    first = []
    for _, _, following in run:
        if following is None or following >= len(statements):
            return []
        first.append(statements[following])
    declaration = f'{kind} {array}[{len(run)}];'
    children = []
    for family, targets in ((FAMILY, first), (BLOCK_FAMILY, [min(first, key=lambda m: m.start())] * len(first))):
        if family == BLOCK_FAMILY and len({m.start() for m in first}) == 1:
            continue
        edits = []
        if scaffold:
            edits.append((scaffold.start(), scaffold.end(), f'{scaffold["indent"]}{declaration}\n'))
        else:
            ends = declaration_ends(part)
            if not ends:
                return []
            edits.append((ends[-1], ends[-1], f'\n{_indent(part.clean, ends[-1])}{declaration}'))
        before = {}
        for k, target in enumerate(targets):
            before.setdefault(target.start(), []).append(f'{target["indent"]}{array}[{k}] = 0;\n')
        edits += [(at, at, ''.join(lines)) for at, lines in before.items()]
        children.append((family, edit(part.source, edits)))
    return children


def _globals(source):
    return set(re.findall(rf'(?m)^\s*extern\s+[^;(]*?\b({IDENT})\s*;', source))


def _indent(clean, at):
    line = clean.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', clean[line:]).group(0)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 1600}
