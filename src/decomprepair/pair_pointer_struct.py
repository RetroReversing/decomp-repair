"""Two neighbouring scalar globals reached through a pointer, written as the two members of a record.

`pa = &G; pb = pa + 1; ... *pa = x; ... *pb = y;` stores through a plain `int *`, and GCC cannot tell that the store
leaves another global alone, so a load of that global (a loop counter) stays below the store: after register
allocation the second scheduler sees an unknown register address next to a fixed one. A member of a record is a
different kind of reference: a store to `p->a` at a register address never conflicts with a plain global at a fixed
address (sched.c: a MEM_IN_STRUCT reference at a varying address against one at a fixed address), so the load moves
above it, where the target has it. The game's C kept the pair as a two-word record; the symbols are split only because
the decompiler named each word. 410 -> 0 in one 242-instruction heightmap filter, with the counter reread between
four stores through the pair, KMC GCC 2.7.2.

A proposal takes `X = &G;` (an `extern` integer global) followed by `Y = X + 1;`, with `X` and `Y` declared as
pointers to the same integer type and `*X` used at least twice. It declares `typedef struct { T a; T b; } PairG;`
above the function, makes `X` a `PairG *` set to `(PairG *) &G`, writes `*X` as `X->a` and `Y` as `&X->b`. At most 2
proposals."""
import re

from .csource import find
from .integer_repair_support import INTEGER, edit, view

FAMILY = 'pair_pointer_struct'
FAMILIES = (FAMILY,)
LIMIT = 2

_ID = r'[A-Za-z_]\w*'
_SET = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<x>{_ID})[ \t]*=[ \t]*&[ \t]*(?P<g>{_ID})[ \t]*;[ \t]*\n'
                  rf'(?P<again>[ \t]*)(?P<y>{_ID})[ \t]*=[ \t]*(?P=x)[ \t]*\+[ \t]*1[ \t]*;[ \t]*\n')
_EXTERN = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{INTEGER})\s+(?P<name>{_ID})\s*;')
_POINTER = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{INTEGER})[ \t]*\*[ \t]*(?P<name>{_ID})[ \t]*;[ \t]*$')


_TYPE_WORDS = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'f32', 'f64', 'int', 'char', 'short', 'long', 'unsigned', 'signed',
               'const', 'volatile', 'void', 'float', 'double'}


def _derefs(body, x):
    """Each `*x` that is a dereference: not a product (`a * x`, `f(a) * x`), but yes after a cast (`(f32) *x`)."""
    found = []
    for use in re.finditer(rf'\*[ \t]*{re.escape(x)}\b', body):
        before = body[:use.start()].rstrip()
        if before.endswith(')'):
            depth, at = 0, len(before)
            while at > 0:
                at -= 1
                depth += (before[at] == ')') - (before[at] == '(')
                if depth == 0:
                    break
            words = re.findall(r'[A-Za-z_]\w*', before[at + 1:-1])
            if not words or not (set(words) <= _TYPE_WORDS or before[at + 1:-1].rstrip().endswith('*')):
                continue
        elif before and (before[-1].isalnum() or before[-1] in '_]'):
            continue
        found.append(use)
    return found


def variants(source, name, header=''):
    """Proposals: a pointer to a global and the pointer one word past it, as a record pointer and its second member."""
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    kinds = {hit['name']: hit['type'] for hit in _EXTERN.finditer(header + '\n' + part.clean[:part.opening])}
    pointers = {hit['name']: hit for hit in _POINTER.finditer(part.clean, part.opening + 1, part.end)}
    out = []
    for hit in _SET.finditer(part.clean, part.opening + 1, part.end):
        x, y, glob = hit['x'], hit['y'], hit['g']
        if glob not in kinds or x not in pointers or y not in pointers or x == y:
            continue
        kind = kinds[glob]
        if ' '.join(pointers[x]['type'].split()) != ' '.join(kind.split()) or pointers[y]['type'] != pointers[x]['type']:
            continue
        base = pointers[x].end()
        body = part.clean[base:part.end]
        uses = _derefs(body, x)
        plain = body
        for use in reversed(uses):
            plain = plain[:use.start()] + ' ' + plain[use.end():]
        if len(uses) < 2 or re.search(rf'\b{re.escape(x)}\b\s*(?:\+\+|--|[-+]=|\[)|(?:\+\+|--)\s*{re.escape(x)}\b', plain):
            continue
        record = f'Pair_{glob}'
        if re.search(rf'\b{record}\b', source):
            continue
        edits = [(span[0], span[0], f'typedef struct {{ {kind} a; {kind} b; }} {record};\n\n'),
                 (pointers[x].start('type'), pointers[x].end('name'), f'{record} *{x}'),
                 (hit.start(), hit.end(), f"{hit['indent']}{x} = ({record} *) &{glob};\n{hit['again']}{y} = &{x}->b;\n")]
        edits += [(base + use.start(), base + use.end(), f'{x}->a') for use in uses]
        out.append((FAMILY, edit(source, edits)))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
