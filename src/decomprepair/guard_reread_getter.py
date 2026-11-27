"""A field guarded, read again into a local and guarded again: the second read through an inline getter.

    if (obj->type != NONE) {                    static inline int f_or_none(T *p) {
        type = obj->type;                           if (p->type != NONE) { return p->type; }
        ...                             ->          return NONE;
        radius = table[type] * obj->scale;      }
        if (type != NONE) {                         type = f_or_none(obj);

The target loads the field twice, once for the first test and again for the local that is indexed and tested a
second time. Written as a plain copy, cse reuses the first load (`move` for the second `lhu`), and a `volatile`
read adds an `andi` of its own. Through an inline function that tests the field itself, the second load stays and
nothing else is emitted: the function's labels end the extended block cse reads across (hypothesis, not read in
cse.c). SN GCC 2.8.1, `-G0 -mips3 -O2`, a 147-instruction N64 pool search: the same getter took the saved best
2327 -> 2107, a rewritten source 200 -> 0.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view

FAMILY = 'guard_reread_getter'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 3
CONSTANT = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uU]?|-1|NULL'
# a field of one pointer: `p->f`, `p->f.g`, m2c's `M2C_FIELD(p, T *, K)`, or `*(T *)((char *)p + K)`
READ = (rf'(?:M2C_FIELD\(\s*{IDENT}\s*,\s*[\w ]+[\s*]*\*\s*,\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\)'
        rf'|\(\s*\(\s*{IDENT}\s*\*\s*\)\s*{IDENT}\s*\)->{IDENT}'
        rf'|{IDENT}->{IDENT}(?:\.{IDENT})*'
        rf'|\*\s*\(\s*[\w ]+\*\s*\)\s*\(\s*\(\s*(?:char|[su]8)\s*\*\s*\)\s*{IDENT}\s*\+\s*'
        rf'(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\))')


def _base(read):
    for pattern in (rf'M2C_FIELD\(\s*({IDENT})', rf'\*\s*\)\s*({IDENT})\s*\)->', rf'(?<![\w)])({IDENT})->',
                    rf'\*\s*\)\s*({IDENT})\s*\+'):
        hit = re.search(pattern, read)
        if hit:
            return hit
    return None


def _pointer_type(part, name, base):
    """The declared pointer type of a parameter or local, as written."""
    head = part.clean[:part.opening]
    signature = head[head.rfind(name):]
    text = signature + part.body
    hit = re.search(rf'(?:^|(?<=[(,;{{}}]))\s*((?:(?:struct|union|unsigned|signed|const)\s+)*{IDENT})\s*(\*+)\s*'
                    rf'{base}\s*(?=[,);=])', text)
    return f'{hit[1]} {hit[2]}' if hit else None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    body, shift = part.body, part.opening + 1
    result, seen = [], set()
    for guard in re.finditer(rf'\bif\s*\(\s*({READ})\s*!=\s*({CONSTANT})\s*\)\s*{{', body):
        read, constant = guard[1], guard[2]
        copy = re.compile(rf'(?<![\w.>])({IDENT})\s*=\s*{re.escape(read)}\s*;').search(body, guard.end())
        if not copy or (read, copy[1]) in seen:
            continue
        seen.add((read, copy[1]))
        local = copy[1]
        # (the getter answers an int: only an integer local reads the same value through it)
        if not re.search(rf'\b{INTEGER}\s+{local}\s*;', body):
            continue
        again = re.compile(rf'\bif\s*\(\s*{local}\s*[!=]=\s*{re.escape(constant)}\s*\)').search(body, copy.end())
        base = _base(read)
        if not again or not base:
            continue
        pointer = _pointer_type(part, name, base[1])
        if not pointer:
            continue
        getter = f'__repair_{local}_or_none'
        while re.search(rf'\b{getter}\b', part.clean):
            getter += '_'
        inner = read[:base.start(1)] + 'p' + read[base.end(1):]
        helper = (f'static inline int {getter}({pointer}p) {{\n    if ({inner} != {constant}) {{\n'
                  f'        return {inner};\n    }}\n    return {constant};\n}}\n')
        at = max(m.start() for m in re.finditer(rf'\b{name}\s*\(', part.clean[:part.opening]))
        at = source.rfind('\n', 0, at) + 1
        start = shift + copy.start()
        result.append((FAMILY, edit(source, [(at, at, helper),
                                             (start, shift + copy.end(), f'{local} = {getter}({base[1]});')])))
        if len(result) >= MAX_CHILDREN:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
