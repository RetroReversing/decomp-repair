"""A guarded do-while that stores through byte cursors beside a counter, written as a `for` loop indexing the bases.

m2c writes a loop that fills two buffers at a fixed offset as a counter, one `void *` cursor per buffer, each stepped
in bytes, and the store address often staged in a temporary:

    i = 0;
    if (count != 0) {
        a = gFirst;                                 for (i = 0; i < (u32) count; i++) {
        b = gSecond;                                    ((u16 *) gSecond)[i * 4 + 0x800] =
        do {                              ->                ((u16 *) gFirst)[i * 4 + 0x800] = 0xFFFF;
            t = a + 0x1000;                        }
            *t = 0xFFFF;
            i += 1;
            a += 8;
            ...
        } while (i < (u32) count);
    }

The game indexed the bases with the counter, and the compiler's loop pass made the cursors, hoisted the large offset and
the constant, and copied the loop's bound itself. Measured with SN GCC 2.8.1 (`-G0 -mips3 -O2 -mfp64`) on a
23-instruction N64 fill of two buffers: 580 with the cursors, 0 as the indexed loop with the two stores chained (310
as two statements). A literal that does not fit the store's signed type makes the element unsigned (`0xFFFF` through
`s16 *` loads -1, through `u16 *` the target's `ori`).

Offered only when the meaning is the same: the counter is zeroed in front of a guard with no `else`; the guarded block
is nothing but `cursor = name;` statements and the loop; the loop body is nothing but one counter step, one constant
step per cursor, the staged addresses and stores of literals or plain names through the cursors; the cursors and
temporaries are named nowhere else; offsets and steps divide by the element's size; and the guard is false exactly when
the `for` loop's first test is (an unsigned compare against the same name, or a `> 0` guard). The stores are offered as
separate statements and, when they store one value, as a chain in either order. That a store into the buffers never
changes the base or bound variables is assumed, as the original's indexed loop would. Proposals only; the judge decides.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'byte_cursor_fill_loop'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_SIZE = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4}
_UNSIGNED = {'s8': 'u8', 's16': 'u16', 's32': 'u32'}
_SIGNED_LIMIT = {'s8': 0x7F, 's16': 0x7FFF, 's32': 0x7FFFFFFF}
_BYTE = r'(?:void|s8|u8|char)'
_ZERO = re.compile(rf'(?<=[;{{}}])\s*(?P<counter>{IDENT})\s*=\s*0\s*;\s*if\s*(?=\()')
_LOOP = re.compile(r'\s*(?P<starts>(?:[A-Za-z_]\w*\s*=\s*[A-Za-z_]\w*\s*;\s*)+)do\s*(?=\{)')
_WHILE = re.compile(r'\s*while\s*(?=\()')
_FIELD = rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>{IDENT})\s*\*\s*,\s*(?P<offset>{_NUMBER})\s*\)'
_CAST = (rf'\*\s*\(\s*(?P<type>{IDENT})\s*\*\s*\)\s*\(\s*(?:\(\s*{_BYTE}\s*\*\s*\)\s*)?(?P<base>{IDENT})\s*\+\s*'
         rf'(?P<offset>{_NUMBER})\s*\)')
_DIRECT = (re.compile(_FIELD + r'\s*=\s*(?P<value>[^=]+)'), re.compile(_CAST + r'\s*=\s*(?P<value>[^=]+)'))
_THROUGH = re.compile(rf'(?:\(\s*\*\s*(?P<a>{IDENT})\s*\)|\*\s*(?P<b>{IDENT}))\s*=\s*(?P<value>[^=]+)')
_STAGE = re.compile(rf'(?P<temp>{IDENT})\s*=\s*(?:\(\s*{IDENT}\s*\*\s*\)\s*)?(?:\(\s*(?:\(\s*{_BYTE}\s*\*\s*\)\s*)?'
                    rf'(?P<inner>{IDENT})\s*\+\s*(?P<inner_offset>{_NUMBER})\s*\)|(?:\(\s*{_BYTE}\s*\*\s*\)\s*)?'
                    rf'(?P<base>{IDENT})\s*\+\s*(?P<offset>{_NUMBER}))')


def _number(text):
    text = text.rstrip('uUlL')
    return int(text, 16 if text[:2].lower() == '0x' else 8 if len(text) > 1 and text[0] == '0' else 10)


def _declaration(body, name):
    """(match of the declaration line, its type, whether a pointer) of the one local `name`, or None."""
    found = list(re.finditer(rf'(?m)^[ \t]*(?P<type>{IDENT})[ \t]*(?P<star>\*?)[ \t]*\b{name}\b[ \t]*;[ \t]*\n', body))
    found = [hit for hit in found if hit['type'] not in ('return', 'goto')]
    return (found[0], found[0]['type'], bool(found[0]['star'])) if len(found) == 1 else None


def _counter_step(statement, counter):
    return re.fullmatch(rf'{counter}\s*\+\+|\+\+\s*{counter}|{counter}\s*\+=\s*1|{counter}\s*=\s*{counter}\s*\+\s*1',
                        statement)


def _walk(statements, counter, bases, body):
    """(steps by cursor, [(base, byte offset, type, value)]) for a loop body, or None when anything else is in it."""
    steps, temps, stores, counted = {}, {}, [], 0
    for statement in statements:
        if _counter_step(statement, counter):
            counted += 1
            continue
        step = re.fullmatch(rf'(?P<p>{IDENT})\s*(?:\+=|=\s*(?P=p)\s*\+)\s*(?P<step>{_NUMBER})', statement)
        if step and step['p'] in bases:
            if step['p'] in steps:
                return None
            steps[step['p']] = _number(step['step'])
            continue
        stage = _STAGE.fullmatch(statement)
        if stage and (stage['inner'] or stage['base']) in bases:
            base = stage['inner'] or stage['base']
            # a staged address is in the cursor's bytes: the cursor itself must step bytes, or be cast to them
            kind = _declaration(body, base)
            if not kind or not kind[2] or not re.fullmatch(_BYTE, kind[1]) or stage['temp'] in bases:
                return None
            temps[stage['temp']] = (base, _number(stage['inner_offset'] or stage['offset']), base in steps)
            continue
        through = _THROUGH.fullmatch(statement)
        if through and (through['a'] or through['b']) in temps:
            temp = through['a'] or through['b']
            base, offset, stepped = temps[temp]
            kind = _declaration(body, temp)
            if not kind or not kind[2]:
                return None
            stores.append((base, offset, stepped, kind[1], through['value'].strip()))
            continue
        direct = next((hit for hit in (p.fullmatch(statement) for p in _DIRECT) if hit), None)
        if not direct or direct['base'] not in bases:
            return None
        stores.append((direct['base'], _number(direct['offset']), direct['base'] in steps, direct['type'],
                       direct['value'].strip()))
    if counted != 1 or not stores or set(steps) != set(bases):
        return None
    # an address taken after its cursor stepped is one step further on
    return temps, [(base, offset + (steps[base] if stepped else 0), kind, value)
                   for base, offset, stepped, kind, value in stores], steps


def _bounds(guard, bound, counter, body):
    """The spellings of the `for` loop's bound that are false at the start exactly when `guard` is, or none."""
    declared = _declaration(body, counter)
    unsigned = bool(re.match(r'\(\s*u(?:32|16|8)\s*\)', bound) or declared and declared[1] in ('u32', 'u16', 'u8'))
    positive = re.fullmatch(r'(?P<x>.+?)\s*>\s*0|0\s*<\s*(?P<y>.+)', guard, re.S)
    nonzero = re.fullmatch(r'(?P<x>.+?)\s*!=\s*0|0\s*!=\s*(?P<y>.+)', guard, re.S)
    if positive:
        tested = (positive['x'] or positive['y']).strip()
    elif unsigned:
        tested = (nonzero['x'] or nonzero['y']).strip() if nonzero else guard
    else:
        return []
    limit = re.sub(r'^\(\s*[su](?:32|16|8)\s*\)\s*', '', bound)
    names = re.findall(r'[A-Za-z_]\w*', limit)
    if not names or names[-1] not in re.findall(r'[A-Za-z_]\w*', tested) or '(' in limit and '*' not in limit:
        return []
    found = [bound]
    if re.sub(r'\s+', '', tested) != re.sub(r'\s+', '', limit):
        # the guard read the bound another way (a word where the declaration says narrower): the target's one load
        cast = re.match(r'\(\s*[su](?:32|16|8)\s*\)\s*', bound)
        found.insert(0, (cast.group() if cast else '') + tested)
    return found


def _element(base, offset, step, kind, value):
    size = _SIZE.get(kind)
    if not size or offset % size or step % size or step < size:
        return None
    if re.fullmatch(_NUMBER, value) and kind in _UNSIGNED and _number(value) > _SIGNED_LIMIT[kind]:
        kind = _UNSIGNED[kind]
    return kind, step // size, offset // size


def variants(source, name):
    """Every guarded byte-cursor store loop written as the indexed `for` loop: statements, then chains."""
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    for head in _ZERO.finditer(clean, part.opening, part.end):
        counter = head['counter']
        opened = head.end()
        closed = close(clean, opened, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, closed) if closed else None
        end = close(clean, brace.end() - 1, '{', '}') if brace else None
        if not end or re.match(r'\s*else\b', clean[end:]):
            continue
        guarded = _LOOP.match(clean, brace.end())
        if not guarded:
            continue
        loop_end = close(clean, guarded.end(), '{', '}')
        tail = _WHILE.match(clean, loop_end) if loop_end else None
        test_end = close(clean, tail.end(), '(', ')') if tail else None
        if not test_end or not re.fullmatch(r'\s*;\s*\}', clean[test_end:end]):
            continue
        inner = clean[guarded.end() + 1:loop_end - 1]
        if '{' in inner:
            continue
        starts = re.findall(rf'({IDENT})\s*=\s*({IDENT})\s*;', guarded['starts'])
        bases = dict(starts)
        if len(bases) != len(starts) or counter in bases:
            continue
        walked = _walk([s.strip() for s in inner.split(';') if s.strip()], counter, bases, body)
        if not walked:
            continue
        temps, stores, steps = walked
        # the cursors and temporaries live only here: each is named in its declaration and inside the replaced span
        span = clean[head.start():end]
        locals_ = list(bases) + list(temps)
        declarations = [_declaration(body, local) for local in locals_]
        if not all(declarations) or any(
                len(re.findall(rf'\b{local}\b', body)) != len(re.findall(rf'\b{local}\b', span)) + 1
                for local in locals_):
            continue
        guard = source[opened + 1:closed - 1].strip()
        test = re.fullmatch(rf'{counter}\s*<\s*(?P<bound>.+)', source[tail.end() + 1:test_end - 1].strip(), re.S)
        if not test or set(bases.values()) & ({counter} | set(locals_)):
            continue
        lvalues, values = [], []
        for base, offset, kind, value in stores:
            element = _element(base, offset, steps[base], kind, value)
            if not element or not re.fullmatch(rf'-?{_NUMBER}|{IDENT}', value) or value in locals_ + [counter]:
                break
            kind, stride, first = element
            index = counter if stride == 1 else f'{counter} * {stride}'
            if first:
                index += f' + {hex(first) if first > 9 else first}'
            lvalues.append(f'(({kind} *) {bases[base]})[{index}]')
            values.append(value)
        if len(lvalues) != len(stores):
            continue
        indent = re.search(r'(?m)^[ \t]*(?=if\b)', source[head.start():opened])
        indent = indent.group() if indent else '    '
        unit = indent + '    '
        bodies = [''.join(f'{unit}{lvalue} = {value};\n' for lvalue, value in zip(lvalues, values))]
        if len(lvalues) > 1 and len(set(values)) == 1:
            # the chain's innermost target is stored first
            bodies.insert(0, f'{unit}{" = ".join(lvalues[::-1])} = {values[0]};\n')
            bodies.append(f'{unit}{" = ".join(lvalues)} = {values[0]};\n')
        children = []
        for bound in _bounds(guard, test['bound'].strip(), counter, body):
            for text in bodies:
                loop = (f'\n{indent}for ({counter} = 0; {counter} < {bound}; {counter}++) {{\n{text}{indent}}}')
                child = source[:head.start()] + loop + source[end:]
                for local in locals_:
                    hit = _declaration(child[part.opening:], local)
                    if hit:
                        at = part.opening + hit[0].start()
                        child = child[:at] + child[part.opening + hit[0].end():]
                children.append((FAMILY, child))
        if children:
            return children
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 57}
