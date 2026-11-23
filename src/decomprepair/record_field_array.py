"""Parallel `D_XXXXXXXX` tables read through one stepped byte offset, written as one array of records indexed by the counter.

m2c names each field of a global record array by its own address and walks them with a byte offset that steps by the
record's size beside the loop's counter:

    for (i = 0, off = 0; i < 4U; i++) {                     for (i = 0; i < 4U; i++) {
        f(*(s16 *)((char *)&D_800C7E10 + off),       ->         f(D_800C7E10[i].x_0, D_800C7E10[i].x_2,
          *(s16 *)((char *)&D_800C7E12 + off),                    D_800C7E10[i].x_8, D_800C7E10[i].x_4);
          *(u16 *)((char *)&D_800C7E18 + off),              }
          *(s32 *)((char *)&D_800C7E14 + off));
        off += 0xC;
    }

GCC 2.7 builds `D[i].f` as `i * 12` in a register plus the symbol: the four products are one giv, reduced to one
register stepped by 12 whose initialisation the loop pass emits with the other reduced givs, after the constants it
hoists (`lui $s7, 0x8000` then `move $s0, $zero`, as in the target), and each read stays `lui %hi(D); addu; lh %lo(D)`.
The user's offset local is a biv whose initialisation stays in front of the hoisted constants (two reordered rows). On
a 1133-instruction effect spawner (KMC GCC 2.7.2) the record array took the last order rows away: 185 -> 125. A sum
written as `(char *)&D + i * 12` instead is a giv with the symbol in it and gets a pointer of its own per field (worse
by thousands); only the array-of-records spelling gives the register product. The reading of loop.c is a hypothesis
from the `-dL` dump.

Taken only when: the offset is set to 0 once (a statement or the `for` initialiser), stepped by one constant K once in
the loop and read nowhere but in `*((T *) (((char *) (&D_ADDR)) + off))`; the loop's counter starts at 0 and steps by
one; there are two or more symbols, all named by their address, within K bytes of the lowest, each read with one
scalar type at a naturally aligned offset; a record of those fields is exactly K bytes; and the lowest symbol is not
named anywhere else (its declaration becomes the array's). The record type is local to the candidate (`Rec_D_...`).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'record_field_array'
FAMILIES = (FAMILY,)

SIZE = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
        'float': 4}
_READ = (r'\*\s*\(\(\s*(?P<type>[A-Za-z_]\w*)\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*\(\s*&\s*(?P<sym>D_[0-9A-Fa-f]{8})'
         r'\s*\)\s*\)\s*\+\s*{off}\s*\)\s*\)')
_STEP_ONE = r'(?:{i}\s*\+\+|\+\+\s*{i}|{i}\s*\+=\s*1[uU]?|{i}\s*=\s*{i}\s*\+\s*1[uU]?)'


def _loop_of(clean, at, start, end):
    """(head start, body open, body close) of the innermost `for`/`do`/`while` loop body around `at`."""
    best = None
    for m in re.finditer(r'\b(for|while|do)\b', clean[start:end]):
        head = start + m.start()
        if m[1] == 'do':
            body = clean.find('{', head)
            if body < 0 or clean[head + 2:body].strip():
                continue
        else:
            paren = clean.find('(', head)
            stop = close(clean, paren, '(', ')') if paren >= 0 else None
            if not stop:
                continue
            body = stop
            while body < end and clean[body].isspace():
                body += 1
            if body >= end or clean[body] != '{':
                continue
        tail = close(clean, body, '{', '}')
        if tail and body < at < tail and (best is None or body > best[1]):
            best = (head, body, tail)
    return best


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for step in re.finditer(r'(?m)^[ \t]*(?P<off>[A-Za-z_]\w*)\s*\+=\s*(?P<k>0[xX][0-9A-Fa-f]+|\d+)\s*;[ \t]*\n',
                            clean[opening:end]):
        off, size = step['off'], int(step['k'], 0)
        at = opening + step.start()
        loop = _loop_of(clean, at, opening, end)
        if not loop:
            continue
        head, body, tail = loop
        reads = list(re.finditer(_READ.replace("{off}", re.escape(off)), clean[opening:end]))
        uses = list(re.finditer(rf'(?<![\w.>]){re.escape(off)}\b', clean[opening:end]))
        init = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(off)}\s*=\s*0\s*[;,)]', clean[opening:end])]
        decls = re.findall(rf'(?m)^[ \t]*(?:register[ \t]+)?[A-Za-z_]\w*[ \t]+{re.escape(off)}[ \t]*;', clean[opening:end])
        if len(init) != 1 or len(uses) != len(reads) + 2 + len(decls) or len(reads) < 2:
            continue
        if not all(body < opening + r.start() < tail for r in reads):
            continue
        fields = {}
        for r in reads:
            fields.setdefault(int(r['sym'][2:], 16), set()).add(r['type'])
        if len(fields) < 2 or any(len(t) != 1 for t in fields.values()):
            continue
        base = min(fields)
        layout = sorted((a - base, next(iter(t))) for a, t in fields.items())
        if any(t not in SIZE or o % SIZE[t] or o + SIZE[t] > size for o, t in layout):
            continue
        align = max(SIZE[t] for _, t in layout)
        if size % align:
            continue
        # the counter: a `for` header's step, or a step in the do-while body, started at 0
        head_text = clean[head:body]
        counter = None
        if head_text.startswith('for'):
            parts = clean[clean.find('(', head) + 1:body].rsplit(')', 1)[0].split(';')
            if len(parts) == 3:
                m = re.fullmatch(r'\s*(?:\+\+\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:\+\+|\+=\s*1[uU]?))\s*', parts[2])
                counter = m and (m[1] or m[2])
        else:
            for m in re.finditer(r'(?m)^[ \t]*(?:\+\+\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:\+\+|\+=\s*1[uU]?))\s*;',
                                 clean[body:tail]):
                counter = m[1] or m[2]
                break
        if not counter or counter == off:
            continue
        if not re.search(rf'(?<![\w.>]){re.escape(counter)}\s*=\s*0\s*[;,]', clean[opening:body]):
            continue
        symbol = f'D_{base:08X}'
        if re.search(rf'\b{symbol}\b', _blank(header or '')):
            continue
        outside = [m for m in re.finditer(rf'\b{symbol}\b', clean) if not any(
            r.start() <= m.start() - opening < r.end() for r in reads)]
        declared = [m for m in re.finditer(rf'(?m)^[ \t]*extern\s+[A-Za-z_][\w \t]*?\b{symbol}\s*;[ \t]*\n', clean)]
        if len(outside) != len(declared) or len(declared) > 1:
            continue
        record = f'Rec_{symbol}'
        members, cursor = [], 0
        for o, t in layout:
            if o > cursor:
                members.append(f'char pad_{cursor:X}[{o - cursor}];')
            members.append(f'{t} x_{o:X};')
            cursor = o + SIZE[t]
        if cursor < size:
            members.append(f'char pad_{cursor:X}[{size - cursor}];')
        typedef = f'typedef struct {{ {" ".join(members)} }} {record};\nextern {record} {symbol}[];\n'
        text = source
        edits = [(opening + r.start(), opening + r.end(), f'{symbol}[{counter}].x_{int(r["sym"][2:], 16) - base:X}')
                 for r in reads]
        edits.append((at, opening + step.end(), ''))
        first = init[0]
        a, b = opening + first.start(), opening + first.end()
        line_start = clean.rfind('\n', 0, a) + 1
        if clean[b - 1] == ';' and not clean[line_start:a].strip():
            edits.append((line_start, b + (1 if clean[b:b + 1] == '\n' else 0), ''))
        elif clean[b - 1] == ',':
            edits.append((a, b + len(re.match(r'\s*', clean[b:])[0]), ''))
        else:
            before = clean.rfind(',', 0, a)
            if before < 0 or clean[before:a].strip(', \t') != '':
                continue
            edits.append((before, b - 1, ''))
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        if declared:
            text = re.sub(rf'(?m)^[ \t]*extern\s+[A-Za-z_][\w \t]*?\b{symbol}\s*;[ \t]*\n', typedef, text, count=1)
        else:
            text = text[:span[0]] + typedef + text[span[0]:]
        out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
