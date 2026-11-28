"""Stack words stored one by one and then passed on as values, written as the vector the game filled and read back.

m2c keeps the value it stored in a temporary and passes the temporary:

    f32 sp40; f32 sp44; f32 sp48;                          f32 sp40[3];
    temp_a = x / k;  sp40 = temp_a;                        temp_a = x / k;  sp40[0] = temp_a;
    sp48 = -15000.0f;                            ->        sp40[2] = -15000.0f;
    temp_b = y / k;  sp44 = temp_b;                        temp_b = y / k;  sp40[1] = temp_b;
    f(m, a, temp_a, temp_b, -15000.0f);                    f(m, a, sp40[0], sp40[1], sp40[2]);

As separate scalars that nothing reads, every one of those stores is dead and deleted, and the call takes the values
from registers. The game had one array: it stored the components and read them back from the stack into the argument
slots. Offered for stack words at consecutive offsets, each assigned once and named nowhere else, whose stored values
are consecutive arguments of one later call, with no other call and no new value for any of them in between, so the
program passes the same values. On an N64 sprite-drawing routine (SN GCC 2.8.1, a position vector handed to a
`guPosition`-shaped call) this took the candidate from 6905 to 5850. Proposals only; the byte judge decides."""
import re

from .integer_repair_support import IDENT, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'stored_stack_run'
FAMILIES = (FAMILY,)
LIMIT = 4
_DECL = re.compile(r'(?m)^[ \t]*(?P<type>f32|s32|u32|float|int)[ \t]+(?P<name>sp(?P<offset>[0-9A-Fa-f]+))[ \t]*;'
                   r'[ \t]*\n')
_CALL = re.compile(rf'(?<![\w.>])(?P<callee>{IDENT})\s*\(')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}


def _trim(clean, start, end):
    text = clean[start:end]
    return start + len(text) - len(text.lstrip()), end - (len(text) - len(text.rstrip()))


def _stores(part):
    """{name: (type, offset, declaration, assignment)} for the stack words that are stored once and never read."""
    clean, found = part.clean, {}
    for decl in _DECL.finditer(clean, part.opening, part.end):
        name = decl['name']
        uses = [m for m in re.finditer(rf'(?<![\w.>])\b{name}\b', clean[:part.end])
                if m.start() >= part.opening and not decl.start() <= m.start() < decl.end()]
        if len(uses) != 1 or clean[:uses[0].start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        store = re.compile(rf'{name}\s*=(?!=)\s*(?P<value>[^;{{}}]+?)\s*;').match(clean, uses[0].start())
        if store and not re.search(rf'{IDENT}\s*\(|\+\+|--|(?<![=!<>])=(?!=)', store['value']):
            found[name] = (decl['type'], int(decl['offset'], 16), decl, store)
    return found


def _run_at(source, part, stores, names):
    """The child that makes `names` (consecutive offsets) one array read back by a later call, or None."""
    clean = part.clean
    values = [source[slice(*stores[n][3].span('value'))].strip() for n in names]
    first = min(stores[n][3].start() for n in names)
    last = max(stores[n][3].end() for n in names)
    for call in _CALL.finditer(clean, last, part.end):
        if call['callee'] in _KEYWORDS:
            continue
        end = close(clean, call.end() - 1)
        if not end:
            continue
        spans = [_trim(clean, call.end() + start, call.end() + stop)
                 for start, stop in split_args(clean[call.end():end - 1])]
        texts = [source[start:end] for start, end in spans]
        at = next((i for i in range(len(texts) - len(values) + 1) if texts[i:i + len(values)] == values), None)
        if at is None:
            continue
        between = clean[first:call.start()]
        if any(m['callee'] not in _KEYWORDS for m in _CALL.finditer(between)) or re.search(r'[{}]', between):
            return None
        for value, name in zip(values, names):
            store = stores[name][3]
            for token in set(re.findall(rf'(?<![\w.>]){IDENT}', value)):
                if re.search(rf'(?<![\w.>])\b{token}\b\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', clean[store.end():call.start()]):
                    return None
        array = names[0]
        decl = stores[array][2]
        indent = re.match(r'[ \t]*', decl[0])[0]
        edits = [(decl.start(), decl.end(), f'{indent}{stores[array][0]} {array}[{len(names)}];\n')]
        edits += [(stores[n][2].start(), stores[n][2].end(), '') for n in names[1:]]
        for index, name in enumerate(names):
            store = stores[name][3]
            edits.append((store.start(), store.start() + len(name), f'{array}[{index}]'))
            edits.append((*spans[at + index], f'{array}[{index}]'))
        return edit(source, edits)
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|volatile)\b', part.body):
        return []
    stores = _stores(part)
    by_offset = {(kind, offset): n for n, (kind, offset, _, _) in stores.items()}
    out, taken = [], set()
    for kind, offset in sorted(by_offset, key=lambda key: key[1]):
        if (kind, offset) in taken:
            continue
        run = []
        while (kind, offset + 4 * len(run)) in by_offset:
            run.append(by_offset[kind, offset + 4 * len(run)])
        taken.update((kind, offset + 4 * i) for i in range(len(run)))
        for length in range(len(run), 1, -1):
            child = _run_at(source, part, stores, run[:length])
            if child:
                out.append((FAMILY, child))
                break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',), 'order': 45}
