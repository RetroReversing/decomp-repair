"""A looked-up pointer tested for NULL, with the count returned through a variable zeroed before the test.

The usual draft of a function that walks an optional object and counts what it wrote:

    model = table[obj->id];
    if (model == NULL) { return 0; }
    count = 0; i = 0; ...
    return count;

SN GCC 2.8.1 (N64, `-G0 -mips3 -O2`) loads `model` into `$v0` and branches round a `j`; a target that loads it into
`$a0`, clears `$v0` in the delay slot of `beqz $a0` and starts the counters with `move $t4, $zero` needed all of:

    u32 result;
    result = obj->id;                           /* the result holds the table address first ($v0 throughout) */
    result = result * 4 + (u32) table;
    model = *(void **) result;
    if (model == NULL) { i = 1; }               /* dead: `i` is set again before any read */
    result = 0;
    if (model != NULL) {
        if (clip != NULL) { i = 1; }            /* dead */
        count = 0; i = 0; ...
        result = count;
    }
    return result;

The empty branches are gone from the object code: their stores are dead, and the jumps go with them. While they are
there, they are labels. The first keeps `result = 0` out of the block that loads the table entry until after register
allocation; the second makes reload's constant reuse forget that `$v0` is zero, so the counters are set from `$zero`
and not copied from `$v0`. Which pass does each is a reading of GCC 2.8.1's sources and its dumps, not proved for
SN's own build. Measured on a 209-instruction N64 mesh walker: 345 -> 0. The dead stores are scaffolding, not what the
game's authors are likely to have typed; the exact judge decides every child.

zero_result_guard
    The early `return 0;` (or the closing `return 0;` after an `if (P != NULL) { .. return V; }`) written as a `u32`
    result set to 0 before `if (P != NULL)`, set to V at the end of the guarded body and returned once. The function
    returns `u32`, so no narrowing is added at the single return.
zero_result_dead_guard
    The same with the two dead branches: one on `P == NULL` before `result = 0;`, one on a pointer parameter the body
    also tests (else on P) at the head of the guarded body. Each stores 1 into a local that the body sets to 0 before
    reading it.
zero_result_index_chain
    The same, and `P = T[I];` written through the result: `result = I; result = result * 4 + (u32) T;
    P = *(TYPE *) result;`.
"""
import re

from .c_scan import close
from .integer_repair_support import edit, view

PLAIN, GUARD, CHAIN = FAMILIES = ('zero_result_guard', 'zero_result_dead_guard', 'zero_result_index_chain')
RESULT = '__repair_result'
LIMIT = 8
_NULL = r'(?:NULL|0)'
_EARLY = re.compile(rf'\bif\s*\(\s*(?:!\s*(?P<bang>[A-Za-z_]\w*)|(?P<name>[A-Za-z_]\w*)\s*==\s*{_NULL})\s*\)\s*'
                    r'(?P<open>\{\s*)?return\s+0\s*;(?(open)\s*\})')
_WRAPPED = re.compile(rf'\bif\s*\(\s*(?P<name>[A-Za-z_]\w*)(?:\s*!=\s*{_NULL})?\s*\)\s*\{{')
_LAST = re.compile(r'(?<![\w.>])return\s+(?P<value>[A-Za-z_]\w*)\s*;\s*\Z')
_NARROW = r'(?:u8|s8|u16|s16|u32|s32|int|unsigned int|unsigned short|unsigned char|short|char)'


def _declared(body, name):
    """The type a local of `body` was declared with, as `u8 *` or `s32`; None when it isn't a plain local."""
    found = re.search(rf'(?m)^[ \t]*(?P<type>(?!return\b|goto\b)[A-Za-z_]\w*)(?P<stars>[\s*]+){name}\s*;', body)
    if not found:
        return None
    stars = found['stars'].count('*')
    return found['type'] + (' ' + '*' * stars if stars else '')


def _scratch(clean, lo, hi, taken):
    """Locals the guarded body sets with `X = 0;` before it names them otherwise: a dead `X = 1;` is safe there."""
    names = []
    for found in re.finditer(r'(?<![\w.>])(?P<name>[A-Za-z_]\w*)\s*=\s*0\s*;', clean[lo:hi]):
        name, before = found['name'], clean[lo:lo + found.start()]
        if name in taken or name in names or re.search(rf'(?<![\w.>]){name}\b', before):
            continue
        if re.search(r'\b(?:if|for|while|do|switch|goto)\b|[A-Za-z_]\w*\s*:', before):
            continue
        names.append(name)
    return names


def _shape(clean, opening, end):
    """(kind, test match, body start, body end, tail start, V) for either spelling of the guard."""
    for found in _EARLY.finditer(clean, opening, end):
        last = _LAST.search(clean[found.end():end])
        if not last:
            continue
        stop = found.end() + last.start()
        if re.search(r'\breturn\b', clean[found.end():stop]):
            continue
        return 'early', found, found.end(), stop, stop, last['value']
    for found in _WRAPPED.finditer(clean, opening, end):
        brace = found.end() - 1
        closing = close(clean, brace)
        if closing < 0 or not re.fullmatch(r'\s*return\s+0\s*;\s*', clean[closing + 1:end]):
            continue
        last = _LAST.search(clean[brace + 1:closing])
        if not last:
            continue
        stop = brace + 1 + last.start()
        if re.search(r'\breturn\b', clean[brace + 1:stop]):
            continue
        return 'wrapped', found, brace + 1, stop, closing, last['value']
    return None


def _build(source, part, end, shape, guard, load):
    """The rewritten function. `guard` = (scratch local, tested pointer) or None; `load` = (span, text) or None."""
    kind, test, lo, stop, tail, value = shape
    name = test['name'] if kind == 'wrapped' or not test['bang'] else test['bang']
    pad = source[source.rfind('\n', 0, test.start()) + 1:test.start()]
    pad = pad if not pad.strip() else '    '
    dead = f'if ({name} == NULL) {{ {guard[0]} = 1; }}\n{pad}' if guard else ''
    inner = f'\n{pad}    if ({guard[1]} != NULL) {{ {guard[0]} = 1; }}' if guard else ''
    opener = f'{dead}{RESULT} = 0;\n{pad}if ({name} != NULL) {{{inner}'
    edits = []
    if load:
        edits.append((load[0][0], load[0][1], load[1]))
    if kind == 'early':
        edits.append((test.start(), test.end(), opener))
        closing = end
        edits.append((stop, closing, f'{RESULT} = {value};\n{pad}}}\n{pad}return {RESULT};\n'))
    else:
        edits.append((test.start(), test.end(), opener))
        edits.append((stop, end, f'{RESULT} = {value};\n{pad}}}\n{pad}return {RESULT};\n'))
    brace = part.opening + 1
    edits.append((brace, brace, f'\n    u32 {RESULT};'))
    return edit(source, edits)


def _index_load(source, part, shape, opening):
    """`P = T[I];` just before the test, as the three statements through the result."""
    kind, test = shape[0], shape[1]
    name = test['name'] if kind == 'wrapped' or not test['bang'] else test['bang']
    clean = part.clean
    found = None
    for found in re.finditer(rf'(?<![\w.>]){name}\s*=(?!=)\s*(?P<table>[A-Za-z_]\w*)\s*\[', clean[:test.start()]):
        pass
    if not found or found.start() < opening:
        return None
    bracket = found.end() - 1
    bracket_end = close(clean, bracket, '[', ']')
    semi = re.compile(r'\s*;\s*').match(clean, bracket_end + 1) if bracket_end >= 0 else None
    if not semi or semi.end() != test.start():
        return None
    kind_of = _declared(clean[opening:], name)
    if not kind_of or not kind_of.endswith('*'):
        return None
    index = source[bracket + 1:bracket_end].strip()
    pad = source[source.rfind('\n', 0, found.start()) + 1:found.start()]
    pad = pad if not pad.strip() else '    '
    text = (f'{RESULT} = {index};\n{pad}{RESULT} = {RESULT} * 4 + (u32) {found["table"]};\n'
            f'{pad}{name} = *({kind_of} *) {RESULT};')
    return (found.start(), clean.index(';', bracket_end) + 1), text


def variants(source, name):
    part = view(source, name)
    if not part or RESULT in source:
        return []
    clean, opening = part.clean, part.opening
    end = close(clean, opening)
    head = re.search(rf'(?<![\w.>])(?P<type>{_NARROW})\s+{re.escape(name)}\s*\(', clean[:opening])
    shape = _shape(clean, opening, end) if head else None
    if not shape:
        return []
    kind, test, lo, stop, _tail, value = shape
    pointer = test['name'] if kind == 'wrapped' or not test['bang'] else test['bang']
    kind_of = _declared(clean[opening:end], pointer)
    if not kind_of or not kind_of.endswith('*') or not re.search(r'\bNULL\b', source):
        return []
    parameters = clean[head.end():opening]
    tested = [p for p in re.findall(r'\*\s*([A-Za-z_]\w*)\s*[,)]', parameters)
              if re.search(rf'\bif\s*\(\s*{p}\s*!=\s*{_NULL}\s*\)', clean[lo:stop])]
    other = tested[0] if tested else pointer

    def widened(child):
        return child[:head.start('type')] + 'u32' + child[head.end('type'):]

    out = [(PLAIN, widened(_build(source, part, end, shape, None, None)))]
    load = _index_load(source, part, shape, opening)
    scratch = _scratch(clean, lo, stop, {pointer, other, value})
    scratch += [value] if value in _scratch(clean, lo, stop, {pointer, other}) else []
    for local in scratch[:3]:
        if load:
            out.append((CHAIN, widened(_build(source, part, end, shape, (local, other), load))))
        out.append((GUARD, widened(_build(source, part, end, shape, (local, other), None))))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
