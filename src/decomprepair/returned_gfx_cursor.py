"""A display-list cursor passed in and handed back, written as libultra's `gSP...(gfx++, ...)` macros.

A `Gfx *f(Gfx *gfx, ...)` routine reads in m2c's draft as stores through the parameter at fixed offsets and an offset
return:

    M2C_FIELD(arg0, s32 *, 0) = 0xDA380001;
    temp_a1 = ...;
    M2C_FIELD(arg0, s32 *, 4) = temp_a1 + 0x80000000;
    g(a, temp_a1, b, arg0);          /* m2c's stray argument: the register the macro's `_g` was left in */
    return arg0 + 8;

The macro is `{ Gfx *_g = (Gfx *)(gfx++); _g->words.w0 = w0; _g->words.w1 = w1; }`: the cursor is copied and advanced
before the words are computed, which gives the target's `move` and the delayed first store. A copy m2c saw still in an
argument register becomes a trailing argument of a later call, which the callee never takes; with the cursor advanced it
would pass another value, so it is dropped (from the call and from the candidate's own prototype) in the same child.
A 46-instruction N64 matrix routine (SN GCC 2.8.1 `-O2`) reached 0 with this after `discarded_result_void` and
`address_global_pointer` (1180 -> 920 -> 680 -> 0).

Applies when a `void *` (or byte pointer) parameter is only used by top-level stores to both words of commands 0..N-1,
in order, by `return p + 8 * N;`, and as the last argument of calls. Between a command's two words only plain local
assignments that do not name the cursor are allowed. Children (`returned_gfx_cursor`): one.
"""
import re

from .csource import _blank, find

FAMILY = 'returned_gfx_cursor'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
WORDS = 'typedef struct { unsigned int w0; unsigned int w1; } RepairGfxWords;\n'
PARAMETER = re.compile(rf'(?:void|u8|s8|char)[ \t]*\*[ \t]*(?P<name>{IDENT})[ \t]*(?=[,)])')
NUMBER = r'(?:0x[0-9A-Fa-f]+|\d+)'
ASSIGNMENT = re.compile(rf'\s*{IDENT} = [^;]*;[ \t]*')


def _stores(body, cursor):
    """{offset: (start, end, value start, value end)} for the `M2C_FIELD(cursor, T *, off) = v;` lines, or None."""
    pattern = re.compile(rf'(?m)^[ \t]*M2C_FIELD\({cursor}, [\w ]+\*+, (?P<off>{NUMBER})\) = (?P<value>[^;\n]+);[ \t]*$')
    found = {}
    for store in pattern.finditer(body):
        offset = int(store['off'], 0)
        if offset in found or body.count('{', 0, store.start()) - body.count('}', 0, store.start()) != 1:
            return None
        found[offset] = (store.start(), store.end(), *store.span('value'))
    return found


def _pure(text, cursor):
    """Only plain local assignments that call nothing and do not name the cursor."""
    if re.search(rf'\b{cursor}\b', text) or re.search(rf'\b(?!sizeof|M2C_FIELD){IDENT}\s*\(', text):
        return False
    while text.strip():
        found = ASSIGNMENT.match(text)
        if not found:
            return False
        text = text[found.end():]
    return True


def _drop_parameter(prefix, callee, count):
    """`prefix` with the last parameter of `callee`'s prototype removed, when it declares `count` of them."""
    found = re.search(rf'(?m)^[^\n;{{]*\b{callee}[ \t]*\((?P<list>[^()\n;]*)\)[ \t]*;', _blank(prefix))
    if not found:
        return prefix
    parts = prefix[found.start('list'):found.end('list')].split(',')
    if len(parts) != count:
        return prefix
    kept = ','.join(parts[:-1]) or 'void'
    return prefix[:found.start('list')] + kept + prefix[found.end('list'):]


def _rewrite(source, clean, span, cursor):
    opening = clean.find('{', span[0], span[1])
    body, text = clean[opening:span[1]], source[opening:span[1]]
    stores = _stores(body, cursor)
    if not stores:
        return None
    count = len(stores) // 2
    if sorted(stores) != [8 * k + part for k in range(count) for part in (0, 4)]:
        return None
    order = [stores[offset] for offset in sorted(stores)]
    if any(first[1] > second[0] for first, second in zip(order, order[1:])):
        return None
    returns = list(re.finditer(rf'\breturn[ \t]+{cursor}[ \t]*\+[ \t]*(?P<size>{NUMBER})[ \t]*;', body))
    if len(returns) != len(re.findall(r'\breturn\b', body)) or not returns or any(
            int(found['size'], 0) != 8 * count or found.start() < order[-1][1] for found in returns):
        return None
    stray = list(re.finditer(rf',[ \t]*{cursor}(?=\)[ \t]*;)', body))
    if any(found.start() < order[0][1] for found in stray):
        return None
    used = len(re.findall(rf'\b{cursor}\b', body))
    if used != 2 * count + len(returns) + len(stray):
        return None
    edits = [(found.start(), found.end(), f'return {cursor};') for found in returns]
    dropped = {}
    for found in stray:
        depth, commas, at = 0, 1, found.start() - 1
        while at >= 0 and not (body[at] == '(' and not depth):
            depth += (body[at] == ')') - (body[at] == '(')
            commas += body[at] == ',' and not depth
            at -= 1
        callee = re.search(rf'({IDENT})\s*$', body[:at])
        if not callee:
            return None
        dropped[callee[1]] = commas + 1
        edits.append((found.start(), found.end(), ''))
    for k in range(count):
        first, second = order[2 * k], order[2 * k + 1]
        between = body[first[1]:second[0]]
        if not _pure(between, cursor):
            return None
        indent = re.match(r'[ \t]*', text[first[0]:])[0]
        inner = indent + '    '
        middle = ''.join(f'\n{inner}{line.strip()}' for line in text[first[1]:second[0]].split('\n') if line.strip())
        block = (f'{indent}{{\n{inner}RepairGfxWords *_g = (RepairGfxWords *){cursor};\n'
                 f'{inner}{cursor} = (void *)((char *){cursor} + 8);\n'
                 f'{inner}_g->w0 = {text[first[2]:first[3]]};{middle}\n'
                 f'{inner}_g->w1 = (unsigned int)({text[second[2]:second[3]]});\n{indent}}}')
        edits.append((first[0], second[1], block))
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    prefix = source[:opening]
    for callee, arguments in dropped.items():
        prefix = _drop_parameter(prefix, callee, arguments)
    start = prefix.rfind('\n', 0, span[0] + 1) + 1 if prefix[span[0]:].strip() else span[0]
    if 'RepairGfxWords;' not in prefix:
        prefix = prefix[:start] + WORDS + prefix[start:]
    return prefix + text + source[span[1]:]


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    head = clean[clean.rfind(name, 0, opening):opening]
    result = []
    for parameter in PARAMETER.finditer(head):
        rewritten = _rewrite(source, clean, span, parameter['name'])
        if rewritten:
            result.append((FAMILY, rewritten))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
