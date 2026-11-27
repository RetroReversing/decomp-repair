"""m2c's chain of byte-stepped temporaries off one cursor, written as the cursor's post-incremented reads.

A run of `lw; addiu cursor, 4` pairs is a loop reading with `*src++`. m2c prints the updated register as temporaries of
their own, as if the sums counted bytes:

    a = M2C_FIELD(p, s32 *, 0);                  a = *p++;
    t1 = p + 4;                                  b = *p++;
    b = M2C_FIELD(p, s32 *, 4);        ->        c = *p++;
    t2 = t1 + 4;                                 d = *p++;
    c = M2C_FIELD(t1, s32 *, 4);
    d = M2C_FIELD(t2, s32 *, 4);
    p = t2 + 4 + 4;

`p` is a pointer to words, so the draft's own `p + 4` steps sixteen bytes in C: the draft was wrong, and no register
spelling of it matches. The child changes what the C computes. It is offered only when every temporary is a `void *`,
the reads are words at offsets 0, 4, 8, ... in order and the final step is exactly four bytes per read.

On an 84-instruction N64 table-setup loop (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) this was the first step of the draft's
route to the match (3472 -> 2765, then the other repairs; one function). The candidate is never a verdict: the judge
decides."""
import re

from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view

FAMILY = 'm2c_cursor_chain'
FAMILIES = (FAMILY,)
_WORD = r'(?:s32|u32|int|f32|M2C_UNK|M2C_UNK32)'
_READ = re.compile(rf'(?P<x>{IDENT})\s*=\s*(?:M2C_FIELD\(\s*(?P<q>{IDENT})\s*,\s*{_WORD}\s*\*\s*,\s*'
                   rf'(?P<k>{NUMBER})\s*\)|\*\s*(?P<plain>{IDENT}))')
_MOVE = re.compile(rf'(?P<t>{IDENT})\s*=\s*(?P<q>{IDENT})(?P<sum>(?:\s*\+\s*{NUMBER})+)')
_STATEMENT = re.compile(r'[^;{}]+;')
LIMIT = 8


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _pointee(clean, name):
    hit = re.search(rf'\b(?P<type>{IDENT})\s*\*\s*{name}\s*;', clean)
    return hit['type'] if hit else None


def _run(statements, at):
    """The chain starting at statement `at`: (cursor, reads, temporaries, index of the last statement) or None."""
    first = _READ.fullmatch(statements[at])
    if not first:
        return None
    cursor = first['q'] or first['plain']
    offsets, reads, temporaries = {cursor: 0}, [], []
    for index in range(at, len(statements)):
        text = statements[index]
        read, move = _READ.fullmatch(text), _MOVE.fullmatch(text)
        if read and (read['q'] or read['plain']) in offsets:
            if read['x'] in offsets:
                return None
            offset = offsets[read['q'] or read['plain']] + (_number(read['k']) if read['k'] else 0)
            reads.append((read['x'], offset))
            continue
        if not move or move['q'] not in offsets:
            return None
        total = offsets[move['q']] + sum(_number(value) for value in re.findall(NUMBER, move['sum']))
        if move['t'] == cursor:
            ordered = [offset for _, offset in reads] == [4 * n for n in range(len(reads))]
            if len(reads) < 2 or not temporaries or not ordered or total != 4 * len(reads):
                return None
            return cursor, [x for x, _ in reads], temporaries, index
        if move['t'] in offsets or any(x == move['t'] for x, _ in reads):
            return None
        offsets[move['t']] = total
        temporaries.append(move['t'])
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    spans = [(m.start() + len(m.group()) - len(m.group().lstrip()), m.end())
             for m in _STATEMENT.finditer(clean, part.opening + 1, part.end - 1)]
    statements = [clean[a:b - 1].strip() for a, b in spans]
    out, at = [], 0
    while at < len(statements) and len(out) < LIMIT:
        found = _run(statements, at)
        if not found:
            at += 1
            continue
        cursor, targets, temporaries, last = found
        first, at = at, last + 1
        adjacent = all(not clean[spans[n][1]:spans[n + 1][0]].strip() for n in range(first, last))
        if not adjacent or _pointee(clean, cursor) is None or not re.fullmatch(_WORD, _pointee(clean, cursor)):
            continue
        body = clean[part.opening:part.end]
        run = clean[spans[first][0]:spans[last][1]]
        if any(_pointee(clean, t) != 'void' or _address_taken(body, t)
               or len(re.findall(rf'\b{t}\b', body)) != len(re.findall(rf'\b{t}\b', run)) + 1
               for t in temporaries) or _address_taken(body, cursor):
            continue
        indent = source[source.rfind('\n', 0, spans[first][0]) + 1:spans[first][0]]
        indent = indent if not indent.strip() else ''
        text = ('\n' + indent).join(f'{x} = *{cursor}++;' for x in targets)
        out.append((FAMILY, edit(source, [(spans[first][0], spans[last][1], text)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
