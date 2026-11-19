"""Three floats m2c copied or passed one by one, as the record the game's source moved whole.

A vector of three floats assigned with `a->pos = *b` is copied by gcc 2.7.2 as three words (`lw`/`sw`), and passed by
value as `f(p, *v)` in three argument registers loaded the same way. m2c writes both as floats:

    M2C_FIELD(arg0, f32 *, 0x24) = (f32) M2C_FIELD(arg2, f32 *, 0);      (x3, offsets +4, +8)
    func_80046424(arg0 + 0x3C, M2C_FIELD(arg1, f32 *, 0), M2C_FIELD(arg1, f32 *, 4), M2C_FIELD(arg1, f32 *, 8));

and gcc then moves them through float registers. An N64 function was 70% so and exact as `*(V *) (dst) = *(V *)
(src)` and `f(p, *(V *) (src))`. Offered only where the target's own instructions move those words as integers:
`sw` at the destination's three offsets for a copy, `lw` into the call's argument registers for a call.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_record_copy'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
FIELD = r'M2C_FIELD\(\s*(?P<{0}>' + IDENT + r')\s*,\s*f32\s*\*\s*,\s*(?P<{0}o>' + NUM + r')\s*\)'
COPY = re.compile(r'(?m)^(?P<indent>[ \t]*)' + FIELD.format('d') + r'\s*=\s*(?:\(\s*f32\s*\)\s*)?'
                  + FIELD.format('s') + r'\s*;[ \t]*\n')
RECORD = 'typedef struct { f32 __repair_v[3]; } __repair_vec3;\n'


def _argument_loads(asm):
    """{(argument register, offset)} for each `lw $aN, offset(...)` in the target."""
    return {(m[1], int(m[2], 0)) for m in re.finditer(r'\blw\s+\$(a[0-3])\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\(', asm or '')}


def _offsets(asm, op):
    return {int(m[1], 0) for m in re.finditer(r'\b' + op + r'\s+\$\w+\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\(', asm or '')}


def _at(base, offset):
    return f'(*(__repair_vec3 *) ((s8 *) ({base}) + {offset}))'


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    stores, loads = _offsets(asm, 'sw'), _argument_loads(asm)
    edits = []
    copies = list(COPY.finditer(clean, opening, end))
    i = 0
    while i + 2 < len(copies):
        a, b, c = copies[i:i + 3]
        offs = [int(m['do'], 0) for m in (a, b, c)]
        srcs = [int(m['so'], 0) for m in (a, b, c)]
        if (a.end() == b.start() and b.end() == c.start() and len({m['d'] for m in (a, b, c)}) == 1
                and len({m['s'] for m in (a, b, c)}) == 1 and offs == [offs[0], offs[0] + 4, offs[0] + 8]
                and srcs == [srcs[0], srcs[0] + 4, srcs[0] + 8] and set(offs) <= stores):
            text = f"{a['indent']}{_at(a['d'], a['do'])} = {_at(a['s'], a['so'])};\n"
            edits.append((a.start(), c.end(), text))
            i += 3
        else:
            i += 1
    # a call passing three consecutive float fields of one pointer, loaded as words
    calls = re.compile(r'\b(?P<f>' + IDENT + r')\s*\((?P<pre>[^;]*?)' + FIELD.format('p') + r'\s*,\s*'
                       + FIELD.format('q') + r'\s*,\s*' + FIELD.format('r') + r'\s*\)')
    for m in calls.finditer(clean, opening, end):
        offs = [int(m[k], 0) for k in ('po', 'qo', 'ro')]
        k = len([p for p in m['pre'].split(',') if p.strip()]) if m['pre'].strip() else 0
        if len({m['p'], m['q'], m['r']}) != 1 or offs != [offs[0], offs[0] + 4, offs[0] + 8] or k > 1 \
                or not {(f'a{k + n}', offs[n]) for n in range(3)} <= loads:
            continue
        start = clean.rfind('M2C_FIELD', 0, m.start('p'))
        edits.append((start, m.end() - 1, _at(m['p'], m['po'])))
        # its prototype takes the record (a K&R `()` one stays as it is)
        proto = re.search(r'(?m)^[^\n;]*\b' + m['f'] + r'\s*\(([^()]*)\)\s*;[^\n]*\n', clean[:span[0]])
        if proto and proto[1].strip() and proto[1].strip() != 'void':
            params = [p.strip() for p in proto[1].split(',')]
            if len(params) >= k + 3:
                params[k:k + 3] = ['__repair_vec3']
                edits.append((proto.start(1), proto.end(1), ', '.join(params)))
    if not edits:
        return []
    text = source
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    text = text[:span[0]] + RECORD + text[span[0]:] if '__repair_vec3;' not in source else text
    # the record type must come before any prototype that names it
    first = re.search(r'\b__repair_vec3\b', text)
    if first and first.start() < text.find(RECORD):
        text = text.replace(RECORD, '')
        text = RECORD + text
    return [(FAMILY, text)]
