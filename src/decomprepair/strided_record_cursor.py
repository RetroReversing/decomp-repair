"""Byte cursors stepped by one stride, written as one pointer to a record of that size.

m2c has no type for a pool of objects, so it walks it with `char *` cursors: the loop pass's own derived pointer
(`other + 0x24`, the one the compiler made to reach the far fields) comes back as a second variable beside the first,
and the loop itself as labels and `goto`s:

    cur = (char *) pool;                                typedef struct { s16 f_0; char pad_2[0x4]; ...
    far = cur + 0x24;                                       char pad_84[0x4]; } __repair_stride_cur;
    loop:                                       ->      cur = (__repair_stride_cur *) pool;
        v = M2C_FIELD(far, s32 *, 0x5C);                do {
        ...                                                 v = cur->f_80;
        far += 0x88;                                        ...
        cur += 0x88;                                        cur += 1;
        if (n >= 100) { goto done; }                    } while (!(n >= 100));
        goto loop;                                      result = 0;
    done: result = 0; return result;                    return result;

The record is only what the accesses show: each field's offset and type, padding between them, and the stride as its
size. A parameter compared with the cursor (`cur != self`) is read as the same record.

An N64 function (SN GCC 2.8.1, `-G0 -mips3 -O2`, 147 instructions; a search of an object pool for one in range):
the saved best, two cursors in a `goto` loop, scored 2327. Folding the derived cursor alone scored 4814 and the
loop alone 4280; the record with the `do`/`while` loop together scored 1730, on the way to 0. So the loop form is
offered as one child with the record.
"""
import re

from .goto_structure_repairs import blocks, parse
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close, negate

FAMILY = 'strided_record_cursor'
LOOP = 'strided_record_loop'
FAMILIES = (FAMILY, LOOP)
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)[uU]?'
BYTE = r'(?:char|signed\s+char|unsigned\s+char|[su]8)'
SIZES = {'char': 1, 'signed char': 1, 'unsigned char': 1, 's8': 1, 'u8': 1, 'short': 2, 'unsigned short': 2,
         's16': 2, 'u16': 2, 'int': 4, 'unsigned int': 4, 's32': 4, 'u32': 4, 'f32': 4, 'float': 4}
MAX_STRIDE = 0x400
MIN_FIELDS = 3


def _number(text):
    return int(re.sub(r'[\suU]', '', text), 0)


def _type(pointer):
    """The pointee of a cast `T *`: a pointer is any 4-byte pointer, an unknown name nothing."""
    text = ' '.join(pointer.split())
    if not text.endswith('*'):
        return None
    text = text[:-1].rstrip()
    if text.endswith('*'):
        return 'void *', 4
    return (text, SIZES[text]) if text in SIZES else None


def _accesses(body, name):
    """(start, end, type, size, offset) of each complete byte-offset access through `name`."""
    found = []
    offset = rf'(?:\s*([+-])\s*({NUMBER}))?'
    for hit in re.finditer(rf'\bM2C_FIELD\(\s*{name}\s*,\s*([\w ]+?[\s*]*\*)\s*,\s*({NUMBER})\s*\)', body):
        typ = _type(hit[1])
        if typ:
            found.append((hit.start(), hit.end(), *typ, _number(hit[2])))
    cast = r'\*\s*\(\s*([\w ]+?[\s*]*\*)\s*\)\s*'
    for pattern in (rf'{cast}{name}\b(?!\s*(?:\[|->|\.|\())', rf'{cast}\(\s*{name}{offset}\s*\)'):
        for hit in re.finditer(pattern, body):
            typ = _type(hit[1])
            if not typ:
                continue
            at = 0
            if hit.lastindex == 3:
                at = _number(hit[3]) * (-1 if hit[2] == '-' else 1)
            found.append((hit.start(), hit.end(), *typ, at))
    return found


def _steps(body, name):
    """The statements `name += S;` and `name = name + S;`."""
    return [(hit.start(), hit.end(), _number(hit[1] or hit[2])) for hit in re.finditer(
        rf'(?<![\w.>]){name}\s*(?:\+=\s*({NUMBER})|=\s*{name}\s*\+\s*({NUMBER}))\s*;', body)]


def _line(body, start, end):
    """The span widened to its whole line when nothing else is on it."""
    first = body.rfind('\n', 0, start) + 1
    last = body.find('\n', end)
    if not body[first:start].strip() and last >= 0 and not body[end:last].strip():
        return first, last + 1
    return start, end


def _cursors(body):
    """Each stepped byte cursor with its declaration, one initialiser and one step."""
    found = {}
    for hit in re.finditer(rf'(?:^|(?<=[;{{}}]))\s*({BYTE})\s*\*\s*({IDENT})\s*;', body):
        name = hit[2]
        steps = _steps(body, name)
        if len(steps) != 1 or not 1 < steps[0][2] <= MAX_STRIDE:
            continue
        inits = [m for m in re.finditer(rf'(?<![\w.>]){name}\s*=(?!=)\s*([^;]+);', body)
                 if (m.start(), m.end()) != steps[0][:2]]
        if len(inits) == 1:
            found[name] = {'decl': (hit.start(1), hit.end()), 'init': inits[0], 'step': steps[0]}
    return found


def _record(source, name):
    part = view(source, name)
    if not part:
        return None
    body = part.body
    if re.search(r'\b(?:volatile|asm|__asm__)\b', body):
        return None
    cursors = _cursors(body)
    derived = {}
    for far, info in cursors.items():
        hit = re.fullmatch(rf'\s*({IDENT})\s*\+\s*({NUMBER})\s*', info['init'][1])
        if hit and hit[1] in cursors and info['step'][2] == cursors[hit[1]]['step'][2]:
            derived[far] = (hit[1], _number(hit[2]))
    for base in (c for c in cursors if c not in derived):
        children = {far: at for far, (root, at) in derived.items() if root == base}
        built = _build(part, name, base, cursors, children)
        if built:
            return built
    return None


def _build(part, name, base, cursors, children):
    body, stride = part.body, cursors[base]['step'][2]
    group = {base: 0, **children}
    # (another pointer compared with the cursor is one of the same objects)
    peers = set()
    for hit in re.finditer(rf'\b{base}\s*[!=]=\s*({IDENT})\b(?!\s*[(\[.]|\s*->)|\b({IDENT})\s*[!=]=\s*{base}\b', body):
        other = hit[1] or hit[2]
        if other != 'NULL' and other not in group and not _steps(body, other):
            peers.add(other)
    uses = []  # (start, end, base, type, offset)
    for pointer, at in [*group.items(), *((p, 0) for p in sorted(peers))]:
        for start, end, typ, size, offset in _accesses(body, pointer):
            uses.append((start, end, pointer, typ, size, at + offset))
    fields = {}
    # the cursor's own spelling of a field names its type; a different one elsewhere reads through a cast
    for _, _, pointer, typ, size, offset in sorted(uses, key=lambda u: u[2] in peers):
        if not 0 <= offset <= stride - size or offset % size:
            return None
        if fields.setdefault(offset, (typ, size))[1] != size:
            return None
    if len(fields) < MIN_FIELDS:
        return None
    layout, at = [], 0
    for offset, (typ, size) in sorted(fields.items()):
        if offset < at:
            return None
        if offset > at:
            layout.append(f'char pad_{at:X}[0x{offset - at:X}];')
        layout.append(f'{typ} f_{offset:X};')
        at = offset + size
    if at < stride:
        layout.append(f'char pad_{at:X}[0x{stride - at:X}];')
    record = f'__repair_stride_{base}'
    if re.search(rf'\b{record}\b', part.clean):
        return None
    spans, edits = [], []  # body spans already accounted for, and (start, end, text)

    def take(start, end, text):
        spans.append((start, end))
        edits.append((start, end, text))

    for start, end, pointer, typ, _, offset in uses:
        through = base if pointer in group else f'(({record} *) {pointer})'
        member = f'{through}->f_{offset:X}'
        take(start, end, member if fields[offset][0] == typ else f'(*({typ} *) &{member})')
    decl, init, step = cursors[base]['decl'], cursors[base]['init'], cursors[base]['step']
    take(decl[0], decl[1], f'{record} *{base};')
    take(init.start(), init.end(), f'{base} = ({record} *) ({init[1].strip()});')
    take(step[0], step[1], f'{base} += 1;')
    for far in children:
        for start, end in (cursors[far]['decl'], (cursors[far]['init'].start(), cursors[far]['init'].end()),
                           cursors[far]['step'][:2]):
            take(*_line(body, start, end), '')
        # (the derived cursor must be set after its base and stepped with it, or the offsets are not constant)
        low, high = sorted((cursors[far]['step'][0], step[0]))
        between = body[low:high]
        if cursors[far]['init'].start() < init.end() or '{' in between or '}' in between or ':' in between:
            return None

    def covered(at):
        return any(start <= at < end for start, end in spans)

    for far in children:
        if any(not covered(hit.start()) for hit in re.finditer(rf'(?<![\w.>]){far}\b', body)):
            return None
    # every other mention of the cursor keeps its meaning under a record pointer: compared, returned or copied
    for hit in re.finditer(rf'(?<![\w.>]){base}\b', body):
        if covered(hit.start()):
            continue
        before, after = body[:hit.start()].rstrip(), body[hit.end():].lstrip()
        if re.match(r'[!=]=', after) or re.search(r'[!=]=$', before):
            continue
        if after.startswith(';') and re.search(r'(?:\breturn|(?<![=!<>+\-*/&|^])=)$', before):
            take(hit.start(), hit.end(), f'(void *) {base}')
            continue
        return None
    return part, record, 'typedef struct { ' + ' '.join(layout) + f' }} {record};\n', edits


def _definition(source, opening, name):
    """The start of the line the definition of `name` begins on."""
    at = max(m.start() for m in re.finditer(rf'\b{name}\s*\(', source[:opening]))
    return source.rfind('\n', 0, at) + 1


def counted_goto_loop(source, name):
    """`L: ...; if (c) { goto X; } goto L;` with `X: ...; return v;` at the function's end, as `do`/`while (!c)`
    followed by X's statements: the only way out of the loop's last statements goes there."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    try:
        top = parse(clean, part.opening + 1, close(clean, part.opening, '{', '}') - 1)
    except ValueError:
        return None
    labels = {s.parts['name']: i for i, s in enumerate(top) if s.kind == 'label'}
    for stmts in blocks(top):
        for last, back in enumerate(stmts):
            if back.kind != 'goto' or last < 2:
                continue
            loop = back.parts['target']
            first = next((i for i, s in enumerate(stmts[:last]) if s.kind == 'label' and s.parts['name'] == loop), None)
            test = stmts[last - 1]
            if first is None or test.kind != 'if' or test.parts.get('other') is not None:
                continue
            then = test.parts['then']['stmts']
            if len(then) != 1 or then[0].kind != 'goto' or then[0].parts['target'] not in labels:
                continue
            if len(re.findall(rf'\bgoto\s+{loop}\s*;', clean)) != 1:
                continue
            out = top[labels[then[0].parts['target']] + 1:]
            if (not out or len(out) > 4 or any(s.kind != 'simple' for s in out)
                    or not clean[out[-1].start:out[-1].end].startswith('return')):
                continue
            start, body_at, body_end = stmts[first].start, stmts[first].end, test.start
            body = clean[body_at:body_end]
            if re.search(r'\b(?:break|continue)\s*;', body):
                continue
            outside = clean[:body_at] + clean[body_end:]
            if any(re.search(rf'\bgoto\s+{label}\s*;', outside) for label in re.findall(rf'\b({IDENT})\s*:(?!:)', body)):
                continue
            condition = clean[test.parts['cond'][0]:test.parts['cond'][1]].strip()
            reverse = negate(condition) or f'!({condition})'
            tail = '\n'.join('    ' + source[s.start:s.end] for s in out)
            inner = source[body_at:body_end].strip('\n').rstrip()
            return (source[:start].rstrip(' \t') + f'    do {{\n{inner}\n    }} while ({reverse});\n{tail}'
                    + source[back.end:])
    return None


def variants(source, name):
    built = _record(source, name)
    if not built:
        return []
    part, record, typedef, edits = built
    shift = part.opening + 1
    changes = [(shift + start, shift + end, text) for start, end, text in edits]
    at = _definition(part.clean, part.opening, name)
    changes.append((at, at, typedef))
    typed = edit(source, changes)
    result = [(FAMILY, typed)]
    looped = counted_goto_loop(typed, name)
    if looped:
        result.insert(0, (LOOP, looped))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
