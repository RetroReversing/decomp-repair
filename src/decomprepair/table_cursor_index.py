"""A cursor stepped through a table beside a counter, written as the counter's index into the table.

m2c drafts `for (i = 0; i < N; i++) { T[i] ... }` as a counter and a separate cursor that both step each pass, and it
writes the cursor's step in bytes whatever the cursor's type (an N64 game's drafts: `s32 *var_v1; ... var_v1 += 4;`
for a 4-byte `addiu`, which compiled as written steps 16 bytes):

    var_a0 = 0;
    var_v1 = &D_800E1A70;
    do {
        *var_v1 = 0;
        var_a0 += 1;
        var_v1 += 4;
    } while (var_a0 < 4U);

This writes every use of the cursor as the table's address at the counter's index, `*(&D_800E1A70 + var_a0) = 0;`, and
drops the cursor, its start and its step. The target's own stride (the step's bytes) is kept, so the result does what
the target does (a step is read as C reads it, elements, unless the target's own immediate says m2c meant bytes): the first child spells the index in the table's own type when its size is the stride (`&G + i`,
the form two matched walks of the game used: docs/learnings walked-table-index), the second in bytes
(`(T *)((u8 *)&G + i * K)`), which needs no declaration.

Offered only when that is the same value at every use: the counter starts at 0 and steps by one, the cursor starts at
the table and steps once a pass, both steps are statements of the loop body itself (not under a branch), nothing in the
body jumps (`goto`, `continue`, `break`, labels), the counter is written nowhere else in the loop, and the cursor is
not read after the loop, has its address taken or is written elsewhere. A use before a step in the body sees that
step's earlier value, and the index says so (`i + 1` when the counter has stepped and the cursor has not, `i - 1` the
other way round).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .pointer_scale_repairs import immediates

FAMILY = 'table_cursor_index'
FAMILIES = (FAMILY,)

ID = r'[A-Za-z_]\w*'
SIZE = {'s8': 1, 'u8': 1, 'char': 1, 'unsigned char': 1, 'signed char': 1, 'M2C_UNK8': 1,
        's16': 2, 'u16': 2, 'short': 2, 'unsigned short': 2, 'M2C_UNK16': 2,
        's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'unsigned': 4, 'long': 4, 'f32': 4, 'float': 4,
        'M2C_UNK': 4, 'M2C_UNK32': 4,
        's64': 8, 'u64': 8, 'f64': 8, 'double': 8, 'long long': 8}
LIMIT = 64000


def _norm(text):
    text = re.sub(r'\b(?:extern|static|const|volatile|register)\b', ' ', text)
    return re.sub(r'\s+', ' ', text).replace(' *', '*').strip()


def _size(kind):
    """Bytes of a declared type: pointers are 4 (the 32-bit consoles these drafts come from), unknown names None."""
    kind = _norm(kind)
    if kind.endswith('*'):
        return 4
    return SIZE.get(kind)


def _declared(text, ident):
    """(type, is array) of `ident`'s declaration in `text`, or None."""
    for m in re.finditer(rf'(?m)^[ \t]*((?:extern\s+|static\s+)?[A-Za-z_][\w \t]*?[\s\*]+)\b{re.escape(ident)}\s*(\[[^\];]*\])?\s*;',
                         text):
        return m[1], bool(m[2])
    return None


def _local(text, ident):
    return re.search(rf'(?m)^[ \t]*([A-Za-z_][\w \t]*?[\s\*]+){re.escape(ident)}\s*;[ \t]*\n?', text)


def _index(counter, shift):
    return counter if not shift else f'{counter} + {shift}' if shift > 0 else f'{counter} - {-shift}'


def _top_level(body, position):
    depth = 0
    for char in re.findall(r'[{}]', body[:position]):
        depth += 1 if char == '{' else -1
    return depth == 0


def _walks(source, clean, a, b, header, immediates):
    for do in re.finditer(r'\bdo\s*{', clean[a:b]):
        opening = a + do.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        tail = re.match(r'\s*while\s*\(([^;]*)\)\s*;', clean[end:b])
        if not tail:
            continue
        loop_end = end + tail.end()
        body = clean[opening + 1:end - 1]
        if re.search(r'\b(?:goto|continue|break|return|switch)\b', body) or re.search(rf'(?m)^[ \t]*{ID}\s*:(?!:)', body):
            continue
        before = clean[a:a + do.start()]
        for step in re.finditer(rf'(?m)^[ \t]*({ID})\s*\+=\s*(0[xX][0-9a-fA-F]+|\d+)\s*;[ \t]*\n?', body):
            cursor, stride = step[1], int(step[2], 0)
            if not stride or not _top_level(body, step.start()):
                continue
            starts = list(re.finditer(rf'(?m)^[ \t]*{re.escape(cursor)}\s*=\s*(&\s*)?({ID})\s*;[ \t]*\n?', before))
            if not starts:
                continue
            start = starts[-1]
            table, address = start[2], bool(start[1])
            between = before[start.end():]
            if re.search(rf'\b{re.escape(cursor)}\b', between):
                continue
            for counter_step in re.finditer(rf'(?m)^[ \t]*({ID})\s*(?:\+=\s*1|\+\+)\s*;[ \t]*\n?', body):
                counter = counter_step[1]
                if counter == cursor or not _top_level(body, counter_step.start()):
                    continue
                zero = list(re.finditer(rf'(?m)^[ \t]*{re.escape(counter)}\s*=\s*0\s*;', before))
                if not zero or re.search(rf'\b{re.escape(counter)}\s*(?:(?:[-+*/%|&^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--|&)\s*{re.escape(counter)}\b',
                                         before[zero[-1].end():]):
                    continue
                others = body[:counter_step.start()] + body[counter_step.end():]
                if re.search(rf'\b{re.escape(counter)}\s*(?:(?:[-+*/%|&^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--|&)\s*{re.escape(counter)}\b', others):
                    continue
                edits = _edits(source, clean, a, b, opening, end, loop_end, tail, body, step, counter_step,
                               start, cursor, stride, table, address, counter, header, immediates)
                if edits:
                    yield edits


def _stride(step, pointee, immediates):
    """The bytes a pass moves the cursor. As C, `p += K` is K elements; m2c writes the step in bytes whatever the
    cursor's type, so the K-byte reading is taken only when the target's own step immediate is K and not K elements."""
    if pointee == 1:
        return step
    if immediates and step in immediates and (not pointee or step * pointee not in immediates):
        return step
    return step * pointee if pointee else None


def _edits(source, clean, a, b, opening, end, loop_end, tail, body, step, counter_step, start, cursor, stride, table,
           address, counter, header, immediates):
    whole = clean[a:b]
    if re.search(rf'\b{re.escape(cursor)}\b', clean[loop_end:b]):
        return None
    body_uses = [m for m in re.finditer(rf'\b{re.escape(cursor)}\b', body)
                 if not step.start() <= m.start() < step.end()]
    condition_uses = list(re.finditer(rf'\b{re.escape(cursor)}\b', tail[1]))
    declaration = _local(source[a:b], cursor)
    if not declaration or not (body_uses or condition_uses):
        return None
    # the cursor: its declaration, its start, its step, its uses in the loop, and nothing else
    if len(re.findall(rf'\b{re.escape(cursor)}\b', whole)) != len(body_uses) + len(condition_uses) + 3:
        return None
    cursor_kind = _norm(declaration[1])
    if not cursor_kind.endswith('*'):
        return None
    stride = _stride(stride, _size(cursor_kind[:-1]), immediates)
    if not stride:
        return None
    for use in body_uses + condition_uses:
        text = body if use in body_uses else tail[1]
        dereferenced = re.search(r'(?:^|[-(=,;{}!&|+<>?:~\s])\*\s*$', text[:use.start()]) and not re.search(r'[\w)\]]\s*\*\s*$', text[:use.start()])
        if ((not dereferenced and re.match(r'\s*(?:(?:[-+*/%|&^]|<<|>>)?=(?!=)|\+\+|--)', text[use.end():]))
                or re.search(r'(?:&|\+\+|--)\s*$', text[:use.start()])):
            return None  # the cursor itself written, stepped or taken: not a plain use of its value
    declared = _declared(source[:a] + '\n' + (header or ''), table)
    if address and declared and not declared[1]:
        base, kind = f'&{table}', _norm(declared[0])
    elif address:
        base, kind = f'&{table}', None
    elif declared and declared[1]:
        base, kind = table, _norm(declared[0])
    elif declared and _norm(declared[0]).endswith('*'):
        base, kind = table, _norm(declared[0])[:-1]
    else:
        return None  # `cursor = table;` with a table that is neither an array nor a pointer we can see
    element = _size(kind) if kind else None
    pointee = cursor_kind[:-1]
    cast = (lambda expr: expr) if kind and kind + '*' == cursor_kind else (lambda expr: f'(({pointee} *){expr})')
    children = []
    for typed in (True, False):
        if typed and element != stride:
            continue  # m2c's step is in bytes: the typed index only when the table's element is that stride
        edits = []
        uses = [(opening + 1 + use.start(), opening + 1 + use.end(),
                 (use.start() > step.start()) - (use.start() > counter_step.start())) for use in body_uses]
        at = end + tail.start(1)
        # the condition is evaluated after both steps: the cursor and the counter are both one pass ahead
        uses += [(at + use.start(), at + use.end(), 0) for use in condition_uses]
        for first, last, shift in uses:
            index = _index(counter, shift)
            if typed:
                expr = cast(f'({base} + {index})')
            else:
                scaled = f'({index}) * {stride}' if shift else f'{counter} * {stride}'
                expr = f'(({pointee} *)((u8 *){base} + {scaled}))'
            edits.append((first, last, expr))
        edits.append((opening + 1 + step.start(), opening + 1 + step.end(), ''))
        edits.append((a + start.start(), a + start.end(), ''))
        edits.append((a + declaration.start(), a + declaration.end(), ''))
        children.append(edits)
    return children


def _apply(source, edits):
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name, asm='', header=''):
    """[(FAMILY, source)]: each walk rewritten (every walk the same way in one child), typed index first. `asm`
    (the target's) says whether a typed cursor's step is m2c's bytes or C's elements (`_stride`)."""
    if not isinstance(source, str) or len(source) > LIMIT:
        return []
    span = find(source, name)
    if not span:
        return []
    a, b = span
    clean = _blank(source)
    walks = list(_walks(source, clean, a, b, header or '', immediates(asm)))
    out = []
    for choice in (0, 1):
        edits, used = [], []
        for children in walks:
            pick = children[min(choice, len(children) - 1)]
            spans = [(s, e) for s, e, _ in pick]
            if any(s < ue and us < e for s, e in spans for us, ue in used):
                continue
            edits += pick
            used += spans
        if edits:
            text = _apply(source, edits)
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header')}
