"""A callback stored into a record and called back through it: the call reads the field into a function-pointer local.

The shape (SN GCC 2.8.1, `-G0 -mips3 -O2`): m2c stores a function's address into a record field and, further on, calls
through a field at the same offset with the record as the argument, with the call written on the field itself:

    M2C_FIELD(o, void (**)(void *), 0xA0) = &func_X;
    ...
    M2C_FIELD(d, void (**)(void *), 0xA0)(d);

The original kept the pointer in a local, assigned twice (the address for the store, the field's value for the call):

    fp = func_X;  M2C_FIELD(o, ..., 0xA0) = fp;  ...  fp = M2C_FIELD(d, ..., 0xA0);  fp(d);

and the pseudo of the local is what places the address build and the call's register: with the field called in place the
target's address is built late or in another register, and the read-back's load goes into the register the call uses.
Reusing the local for the other stores of callbacks measured worse than only the last one, so this offers the call's
read-back alone and the read-back with the store of the callback at that offset, not every store.

The gate is the target's: a `lw rN, OFFSET(base)` of the call's offset followed, within four instructions, by `jalr rN`
(the call goes through the field), and a `lui ..., %hi(func_X)`
for the function the earlier store puts there (the address is built in the function, not copied from elsewhere). Nothing is proposed without
the assembly. Whether the address is built "late" is not visible from the target alone, so the children are few
(at most LIMIT) and the judge decides each.

`variants` finds, after a store of a function's address at the field's offset, a statement that is a call through a field typed `RET (**)(PARAMS)` (`[lhs =] M2C_FIELD(b, T, o)(args);`)
and the earlier stores `M2C_FIELD(b2, T', o) = &func_X;` (or `func_X`) at the same offset of a name declared as a
function (or as m2c's `extern M2C_UNK name;`) in the file. Children:

- `callback_pointer_local`: the call becomes `fp = M2C_FIELD(b, T, o);` and `fp(args);` (`lhs = fp(args);`), `fp`
  declared `RET (*fp)(PARAMS);`;
- `callback_pointer_store`: the nearest earlier store at that offset also goes through it: `fp = &func_X;` and
  `M2C_FIELD(b2, T', o) = fp;`, when the two field types read the same (the pointer's type must match), then the call
  as above (a second assignment to `fp`).

Faithful: the same address is stored, the same field is read and called, nothing is moved across a statement.
This module reads text only and never compiles or judges."""
import re

from .hand_found_support import HIGH, IDENT, LOADS, blocks, declare, fields, fresh, instructions, memory, simple, stmts
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'callback_pointer_local'
STORE_FAMILY = 'callback_pointer_store'
FAMILIES = (FAMILY, STORE_FAMILY)
LIMIT = 4
MAX_STORES = 3
WINDOW = 4
_POINTER = re.compile(r'(?P<ret>.+?)\(\s*\*\*\s*\)\s*\((?P<params>.*)\)', re.S)


def evidence(asm):
    """({offsets the target calls through}, {symbols whose address it builds with lui %hi})."""
    ops = instructions(asm)
    offsets, built = set(), set()
    for index, (op, args) in enumerate(ops):
        if op == 'lui' and len(args) == 2 and HIGH.search(args[1]):
            built.add(HIGH.search(args[1])['symbol'])
        if op not in LOADS or len(args) != 2 or not memory(args[1]):
            continue
        for later, later_args in ops[index + 1:index + 1 + WINDOW]:
            if later in ('jalr', 'jr') and later_args and later_args[-1] == args[0]:
                offsets.add(memory(args[1])[0])
                break
    return offsets, built


def _function_names(source, header):
    return set(re.findall(rf'({IDENT})\s*\([^;{{}}]*\)\s*;', source + '\n' + (header or '')))


def variants(source, name, header='', arch='mips', asm=''):
    if arch != 'mips' or not asm:
        return []
    offsets, built = evidence(asm)
    part = view(source, name) if offsets else None
    if not part:
        return []
    clean = part.clean
    functions = _function_names(clean[:part.opening], header) | _function_names(source[:part.opening], '')
    taken = set(re.findall(IDENT, source)) | set(re.findall(IDENT, header or ''))
    children = []
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        for index, (start, end) in enumerate(spans):
            text = clean[start:end]
            if not simple(text):
                continue
            found = [f for f in fields(clean, start, end) if re.match(r'\s*\(', clean[f.end:end])]
            if len(found) != 1 or found[0].offset not in offsets:
                continue
            field = found[0]
            opening = field.end + clean[field.end:end].index('(')
            closing = close(clean, opening)
            before = re.fullmatch(r'\s*(?:(?P<lhs>[^=;()]+?)\s*=(?!=)\s*)?', clean[start:field.start])
            if not closing or not before or not re.fullmatch(r'\s*;\s*', clean[closing:end]):
                continue
            hit = {'lhs': before['lhs'], 'call': (field.start, field.end), 'args': (opening + 1, closing - 1)}
            pointer = _POINTER.fullmatch(' '.join(field.kind.split()))
            if not pointer:
                continue
            children += _children(source, part, spans, index, hit, field, pointer, built, functions, taken)
    return list(dict.fromkeys(children))[:LIMIT]


def _children(source, part, spans, index, hit, field, pointer, built, functions, taken):
    clean = part.clean
    start, end = spans[index]
    local = fresh('callback', taken, 'fn')
    kind = f'{pointer["ret"].strip()} (*{local})({pointer["params"].strip()});'
    declaration = declare(source, part, [kind])
    if not declaration:
        return []
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
    lhs = hit['lhs'].strip() + ' = ' if hit['lhs'] else ''
    call = source[hit['call'][0]:hit['call'][1]]
    arguments = source[hit['args'][0]:hit['args'][1]]
    readback = (start, end, f'{local} = {call};\n{indent}{lhs}{local}({arguments});')
    out = []
    for at in range(index):  # every earlier store of a function's address at the same offset, the first first
        text = clean[spans[at][0]:spans[at][1]]
        store = re.fullmatch(rf'(?P<lvalue>M2C_FIELD\(.*\))\s*=(?!=)\s*&?\s*(?P<target>{IDENT})\s*;', text, re.S)
        if not store or (store['target'] not in functions and not re.search(rf'\bextern\s+M2C_UNK\s+{store["target"]}\s*;', clean)):
            continue
        written = fields(clean, spans[at][0], spans[at][1])
        if not written or written[0].offset != field.offset or written[0].end != spans[at][0] + store.end('lvalue'):
            continue
        if store['target'] not in built:
            continue  # (the target does not build that function's address here: not this shape)
        a, b = spans[at]
        indent_store = re.match(r'[ \t]*', source[source.rfind('\n', 0, a) + 1:])[0]
        value = ('&' if '&' in clean[a + store.end('lvalue'):a + store.start('target')] else '') + store['target']
        reuse = (a, b, f'{local} = {value};\n{indent_store}{source[a:a + store.end("lvalue")]} = {local};')
        out.append((STORE_FAMILY, edit(source, [declaration, reuse, readback])))
    return ([(FAMILY, edit(source, [declaration, readback]))] + out[:MAX_STORES]) if out else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm'),
          'order': 67, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
