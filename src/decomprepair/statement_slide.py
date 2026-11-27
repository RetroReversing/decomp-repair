"""One simple statement of a straight-line run moved past the independent statements around it.

GCC 2.7.2's first scheduler works backward from the end of a basic block and breaks ties by the original order, and the
register allocator numbers pseudos by first use, so the order of independent statements in one run decides which constant
is materialised first, where a load sits among its siblings and which pseudo wins a tie. m2c emits a run in the order
its own pass met the instructions, which is rarely the order the game's source had. Two slides decided a 132-instruction
table search (KMC `-O2`): `flags |= 0x80800;` after the statement that computes the division (the `lui 0x51eb` pair then
precedes the `lui 8` pair, 295 -> 255), and the halfword reload that stores the high byte moved up beside the first load
(255 -> 195 -> 135 with the byte load first). Each alone moved the judge's score, so a greedy chain finds them one at a time
once something offers the slide.

A child is offered only when the moved statement commutes with every statement it passes: no call, no store through a
pointer other than an `M2C_FIELD(base, type *, offset)` (compared by base, byte interval; the cast spelling
`*((u8 *) (((char *) base) + 0x4A))` and a global's `*((u16 *) (&G))` count as cells too, a global's cell clashing with
any pointer's), no shared local that one writes and the other touches. A byte field read into a local moved below the
next statement's byte store to another field of the same record (`t = *((u8 *) (p + 0x4A)); *((u8 *) (p + 0xC0)) = ..;`
the other way round) put the load where a 1315-instruction sound-sequence interpreter has it, after the store, and left
no `andi` of the local (KMC GCC 2.7.2 `-O2`, 5475 -> 5025). The move is a hypothesis for the scheduler; the judge decides. Bounded to `LIMIT` children,
shortest slides first.

A field spelled through a record cast, `((Emitter *) arg0)->owner = ((Emitter *) arg0)->owner;`, is compared by the
member's byte interval too, laid out from the struct in the source or header. The app's typed m2c drafts write every
field that way, so none of their stores could move: a 78-instruction N64 effect spawner (SN GCC 2.8.1 `-G0 -mips3
-O2`) needed the owner copy of each new record above two constant stores (300 -> 120 -> 0, one arm a step), after
1668 automatic trials had offered nothing.

A statement that only works on a plain local no call can reach (declared, never address-taken, not `volatile`) also
passes a statement with a call that does not name it, and `x += K;` counts as a statement on `x`: the call is a
barrier to the scheduler, so the order against it is the one thing the source decides (a 1133-instruction effect
spawner: `phase += 0.21f;` below the statement that calls `__cosf`, 3555 -> 3215). A float literal on the right of a plain
assignment (`height = 120.0f;`) is a constant like any other, and declarations are not part of a run (their order
is not code): with both, the spawner's `height = 120.0f;` moved above three statements before its copy `var_fs1 =
height;`, so cse no longer swaps the constant into the copy (`(set REG0 REG1)` after the insn that set REG1, cse.c),
80 -> 70. It passes a store through a
member, an array or a pointer that does not name it too: a flag cleared with `kind = 0;` after a call and two stores
(`rec[id].loaded = 1; mode = 1;`) was the target's when cleared above the call (an 874-instruction N64 object spawner,
KMC GCC 2.7.2 `-O2`, 15 -> 0). Set before the call, the flag is live across it, so global.c gives it a saved register
(`$s0`, as the target has) where the later clear left it in `$a1`.

A field of a global in m2c's own spelling, `M2C_FIELD(&D_8007FC64, u8 *, 2)`, is that global's cell (it was refused
for its `&`), kept apart from the plain globals stored beside it unless it is the same symbol or its address overlaps: a
64-instruction N64 routine (SN gcc 2.8.1) wanted a third byte store back beside the other two, above four word clears
(450 alone, 0 with the call's missing arguments).

statement_slide_far
    The slides the `LIMIT` above leaves out, up to `FAR_LIMIT` of them: shortest first, so in a function with two long
    runs of stores every slide of three places was cut. A 66-instruction N64 sound-voice initialiser (SN GCC 2.8.1
    `-G0 -mips3 -O2`) wanted a word store three places down, below three byte stores of constants (110 -> 80, then two
    more reorders to 0); it was the 48th of 78 slides.
"""
import re

from .field_offsets import Types
from .integer_repair_support import IDENT, view

FAMILY = 'statement_slide'
FAR_FAMILY = 'statement_slide_far'
FAMILIES = (FAMILY, FAR_FAMILY)
LIMIT = 40
FAR_LIMIT = 80  # the slides past LIMIT, offered apart as FAR_FAMILY
REACH = 4
FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>[^,*]+?)\s*\*\s*,\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)')
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4}
TYPES = r'(?:s8|u8|s16|u16|s32|u32|f32|int|char|short|long|unsigned|signed)'
CALL = re.compile(rf'\b(?!{TYPES}\b)[A-Za-z_]\w*\s*\(')
CAST_POINTER = re.compile(rf'\(\s*(?:{TYPES}\s*)+\*+\s*\)')
DEREF = re.compile(r'(?:^|[-+*/&|^<>=?:(,!~])\s*\*')
OTHER = re.compile(r'\[|->|\.|\+\+|--|\bvolatile\b')


# The saved bests' spelling of a field, `*((u8 *) (((char *) voice) + 0x4A))`, and of a global read as another width,
# `*((u16 *) (&G))`: written as `M2C_FIELD` cells so they compare by base and byte interval like m2c's own. A global's
# base is `__global_G`, which can never be a local's name; `_clash` keeps it apart from pointers it may alias.
# A byte pointer as m2c's expansions and the app's `M2C_FIELD` define cast it: `(char *)` or `(s8 *)`.
BYTE = r'(?:char|signed\s+char|unsigned\s+char|s8|u8)'
CAST_FIELD = re.compile(rf'\*\s*\(\s*\(\s*(?P<type>{TYPES}(?:\s+{TYPES})*)\s*\*\s*\)\s*\(\s*\(\s*\(\s*{BYTE}\s*\*\s*\)\s*'
                        rf'(?P<base>{IDENT})\s*\)\s*\+\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\)')
CAST_GLOBAL = re.compile(rf'\*\s*\(\s*\(\s*(?P<type>{TYPES}(?:\s+{TYPES})*)\s*\*\s*\)\s*\(?\s*&\s*(?P<sym>{IDENT})\s*\)?\s*\)')
GLOBAL = '__global_'
# The other expansion of `M2C_FIELD`, `*(T *)((char *)(base) + off)`, and the redundant pair of parentheses m2c's
# expansions put around a whole cell: `(*(s8 *)((char *)(arg0) + 0x7A)) = 2;`.
DEREF_FIELD = re.compile(rf'\*\s*\(\s*(?P<type>{TYPES}(?:\s+{TYPES})*)\s*\*\s*\)\s*\(\s*\(\s*{BYTE}\s*\*\s*\)\s*'
                         rf'(?:\(\s*(?P<wrapped>{IDENT})\s*\)|(?P<bare>{IDENT}))\s*\+\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)')
WRAPPED_FIELD = re.compile(r'(?P<call>\w\s*)?\(\s*(?P<field>M2C_FIELD\([^()]*\))\s*\)')  # (a call's parentheses stay)


# A member read or written through a record cast, `((Emitter *) arg0)->owner`: the way an m2c draft types its pointers
# once its fields are written as structs. The record's layout says which bytes it is.
RECORD_CELL = re.compile(rf'\(\s*\(\s*(?P<type>(?:struct\s+)?{IDENT})\s*\*\s*\)\s*(?:\(\s*(?P<wrapped>{IDENT})\s*\)|(?P<bare>{IDENT}))'
                         rf'\s*\)\s*->\s*(?P<member>{IDENT})(?!\s*(?:\.|\[|->))')
CELL_KINDS = {1: 'u8', 2: 'u16', 4: 'u32'}


def _record_cells(text, types):
    """`text` with each `((T *) p)->m` of a 1, 2 or 4 byte member of a struct `T` written as its `M2C_FIELD` cell, for
    reading what the statement touches (the statement itself keeps its spelling). Anything unsized stays as it is, and
    its `->` then keeps the statement from moving."""
    def cell(found):
        record = types.struct(found['type'])
        member = next((m for m in record.members if m.name == found['member']), None) if record else None
        if member is None or member.dims or member.size not in CELL_KINDS:
            return found[0]
        return f'M2C_FIELD({found["wrapped"] or found["bare"]}, {CELL_KINDS[member.size]} *, {member.offset})'
    return RECORD_CELL.sub(cell, text)


# m2c's own spelling of a field of a global, `M2C_FIELD(&G, u8 *, 2)`: the same cell as `*((u8 *) (&G) + 2)`.
ADDRESS_FIELD = re.compile(rf'(?<![\w.>])M2C_FIELD\(\s*&\s*(?P<sym>{IDENT})\s*,')
ADDRESS_NAME = re.compile(r'D_([0-9A-Fa-f]{8})')


def _cells(text):
    text = ADDRESS_FIELD.sub(lambda m: f'M2C_FIELD({GLOBAL}{m["sym"]},', text)
    text = CAST_FIELD.sub(lambda m: f'M2C_FIELD({m["base"]}, {m["type"]} *, {m["off"]})', text)
    text = DEREF_FIELD.sub(lambda m: f'M2C_FIELD({m["wrapped"] or m["bare"]}, {m["type"]} *, {m["off"]})', text)
    text = WRAPPED_FIELD.sub(lambda m: m[0] if m['call'] else m['field'], text)
    return CAST_GLOBAL.sub(lambda m: f'M2C_FIELD({GLOBAL}{m["sym"]}, {m["type"]} *, 0)', text)


def _effects(text):
    """`(writes, reads)` as sets of ('v', name) and ('f', base, lo, hi) keys, or None when the statement is no plain
    assignment of locals and `M2C_FIELD` cells."""
    text = _cells(text)
    depth, split = 0, None
    for pos, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == '=' and depth == 0 and text[pos - 1:pos] not in '=!<>+-*/&|^%' and text[pos + 1:pos + 2] != '=':
            split = pos
            break
    if split is None:
        compound = re.match(rf'\s*({IDENT})\s*(?:[-+*/%&|^]|<<|>>)=(?!=)\s*(.+?)\s*;?\s*$', text, re.S)
        value = re.sub(r'\b\d+\.\d*[fF]?|\B\.\d+[fF]?', '0', compound[2]) if compound else ''  # (float literals)
        if not compound or CALL.search(value) or DEREF.search(value) or OTHER.search(value) or '&' in value:
            return None
        names = {('v', ident) for ident in re.findall(rf'\b{IDENT}\b', value) if ident not in WIDTH}
        return {('v', compound[1])}, names | {('v', compound[1])}
    left, right = text[:split], re.sub(r'\b\d+\.\d*[fF]?|\B\.\d+[fF]?', '0', text[split + 1:])  # (float literals)
    stripped = CAST_POINTER.sub(' ', FIELD.sub(' ', left + ' = ' + right))
    if CALL.search(stripped) or DEREF.search(stripped) or OTHER.search(stripped) or '&' in left:
        return None
    def keys(part):
        out = set()
        for found in FIELD.finditer(part):
            low = int(found['off'], 0)
            out.add(('f', found['base'], low, low + WIDTH.get(found['type'].strip(), 4)))
            out.add(('v', found['base']))
        out |= {('v', ident) for ident in re.findall(rf'\b{IDENT}\b', FIELD.sub(' ', part))
                if ident not in WIDTH and ident not in {'unsigned', 'signed', 'short', 'long', 'void', 'M2C_FIELD'}}
        return out
    lhs_field = FIELD.fullmatch(left.strip())
    writes = {('f', lhs_field['base'], int(lhs_field['off'], 0), int(lhs_field['off'], 0) + WIDTH.get(lhs_field['type'].strip(), 4))} if lhs_field else keys(left)
    reads = keys(right) | (({('v', lhs_field['base'])}) if lhs_field else set())
    return writes, reads


def _global_cell(cell, name):
    """Whether the cell of a global may be the plain global `name`: the same symbol, or (both named by their address)
    one that begins within eight bytes below the cell's end and not before its start."""
    if not cell[1].startswith(GLOBAL):
        return False
    symbol = cell[1][len(GLOBAL):]
    if symbol == name:
        return True
    base, other = ADDRESS_NAME.fullmatch(symbol), ADDRESS_NAME.fullmatch(name)
    if not base or not other:
        return False
    low, at = int(base[1], 16) + cell[2], int(other[1], 16)
    return low - 7 <= at < int(base[1], 16) + cell[3]


def _clash(a, b):
    for x in a:
        for y in b:
            if x[0] == 'v' and y[0] == 'v' and x[1] == y[1]:
                return True
            if {x[0], y[0]} == {'v', 'f'} and _global_cell(x if x[0] == 'f' else y, y[1] if x[0] == 'f' else x[1]):
                return True
            if x[0] == 'f' and y[0] == 'f' and x[1] == y[1] and x[2] < y[3] and y[2] < x[3]:
                return True
            if x[0] == 'f' and y[0] == 'f' and x[1] != y[1] and (x[1].startswith(GLOBAL) != y[1].startswith(GLOBAL)):
                return True  # a global and a pointer's cell may be the same memory
    return False


def commutes(one, two):
    first, second = _effects(one), _effects(two)
    if not first or not second:
        return False
    return not (_clash(first[0], second[0] | second[1]) or _clash(second[0], first[1]))


def commutes_past_call(one, two, locals_):
    """`one` only works on plain locals (never address-taken, so no call or store can reach them) and `two` names none
    of them: the order is then the scheduler's tie-break alone. `two` may hold a call (a barrier the scheduler cannot
    move anything across) or any store through a pointer, an array or a member: none of them can touch a local whose
    address is never taken."""
    first = _effects(one)
    if not first or two.lstrip().startswith(('return', 'goto', 'break', 'continue')):
        return False
    names = {key[1] for key in first[0] | first[1]}
    if any(key[0] != 'v' for key in first[0] | first[1]) or not names <= locals_:
        return False
    return not (names & set(re.findall(rf'\b{IDENT}\b', two)))


def _locals(part):
    """The plain scalar locals and parameters of the function that nothing takes the address of and that are not `volatile`."""
    body = part.clean[part.opening:part.end]
    declared = list(re.findall(rf'(?m)^[ \t]*(?:register\s+)?(?:unsigned\s+)?(?:s8|u8|s16|u16|s32|u32|f32|f64|int|char|short|long|float|double)'
                              rf'[ \t]+({IDENT})[ \t]*;', body))
    # A parameter is as much a local as a declared one (a 131-instruction table walk: `index = start;` above the call
    # after the walk, 295 -> 0).
    signature = part.clean[:part.opening]
    head = signature[signature.rfind('(') + 1:signature.rfind(')')]
    for piece in head.split(','):
        found = re.search(rf'({IDENT})\s*$', piece)
        if found and len(piece.split()) > 1 and 'volatile' not in piece:
            declared = declared + [found[1]]
    return {name for name in declared if not re.search(rf'&\s*{name}\b', body)}


_DECLARATION = re.compile(r'(?:(?:register|static|const|volatile|unsigned|signed|struct|union)\s+)*[A-Za-z_]\w*'
                          r'(?:\s*\*+\s*|\s+)[A-Za-z_]\w*(?:\s*\[[^\]]*\])?')


def _runs(clean, start, end, minimum=3):
    """Maximal runs of consecutive simple `...;` statements, as `[(from, to, [(s, e), ...])]` at one block level."""
    runs = []
    stack = [[]]
    i = start
    while i < end:
        char = clean[i]
        if char == '{':
            stack.append([])
            i += 1
        elif char == '}':
            runs.append(stack.pop())
            i += 1
        elif char.isspace():
            i += 1
        else:
            stop = i
            depth = 0
            while stop < end:
                c = clean[stop]
                depth += (c in '([') - (c in ')]')
                if depth == 0 and c in ';{}':
                    break
                stop += 1
            if stop < end and clean[stop] == ';':
                text = clean[i:stop]
                if (re.match(r'(?:if|for|while|do|else|switch|return|goto|case|default)\b', text)
                        or ':' in text.replace('?', '').replace('::', '') or _DECLARATION.fullmatch(text.strip())):
                    runs.append(stack[-1])
                    stack[-1] = []
                else:
                    stack[-1].append((i, stop + 1))
                i = stop + 1
            else:
                runs.append(stack[-1])
                stack[-1] = []
                i = stop if stop > i else i + 1
    runs.append(stack[0])
    return [run for run in runs if len(run) >= minimum]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    found = []
    safe = _locals(part)
    types = Types(source, header) if '->' in part.clean else None
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end)):
        texts = [source[s:e] for s, e in run]
        read = [_record_cells(text, types) if types else text for text in texts]  # what each statement touches
        for index, text in enumerate(read):
            for step in range(1, REACH + 1):
                for sign in (1, -1):
                    target = index + sign * step
                    if not 0 <= target < len(texts):
                        continue
                    lo, hi = sorted((index, target))
                    between = [read[k] for k in range(lo, hi + 1) if k != index]
                    if all(commutes(text, other) or commutes_past_call(text, other, safe) for other in between):
                        order = list(range(len(texts)))
                        order.insert(target, order.pop(index))
                        pieces = [source[run[k][0]:run[k][1]] for k in order]
                        child = source[:run[0][0]]
                        for k, piece in enumerate(pieces):
                            gap = source[run[k - 1][1]:run[k][0]] if k else ''
                            child += gap + piece
                        child += source[run[-1][1]:]
                        found.append((step, child))
    result = []
    for _, child in sorted(found, key=lambda item: item[0]):
        if child != source and child not in result:
            result.append(child)
        if len(result) >= LIMIT + FAR_LIMIT:
            break
    return [(FAMILY, child) for child in result[:LIMIT]] + [(FAR_FAMILY, child) for child in result[LIMIT:]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
