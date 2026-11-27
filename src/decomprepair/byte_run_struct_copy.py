"""m2c's byte-by-byte load of a small record into neighbouring stack bytes, written back as one record copy.

A local record of bytes initialised from read-only data (`s8 color[3] = {-1, -1, -1};`, or a struct assignment from a
constant record) compiles to a block move: the address in one register, every byte loaded off it, then every byte
stored. m2c has no record, so it names the bytes one at a time:

    temp = &sym + 0x40;
    sp20 = *(s8 *) ((char *) (&sym) + 0x40);
    sp21 = *(s8 *) ((char *) (temp) + 1);
    sp22 = *(s8 *) ((char *) (temp) + 2);
    f(&sp20);

where only `sp20` escapes (the run must start at such a byte), so the other two stores are dead and the loads interleave with their stores. Written as one
copy of a record of that size, `struct { s8 b[3]; } sp20; sp20 = *(__typeof__(sp20) *) ADDRESS;`, the compiler's block
move comes back without reading any game data (SN GCC 2.8.1, `-O2`, a 51-instruction N64 menu list: 1560 -> 250 from
this edit alone, and exact with `stride_cursor_index`).

`byte_run_struct_copy`: two to eight `s8`/`u8`/`char` locals at consecutive `spXX` offsets, each assigned once from the
byte at the same position behind one address (written out, or through a pointer temporary set to it), with only plain
scalar assignments between the reads. Every other use of the locals becomes the record's bytes. The temporary goes
when nothing else names it. A candidate only: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'byte_run_struct_copy'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_BYTE = r'(?:s8|u8|char|signed char|unsigned char)'
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{_BYTE})\s+sp(?P<off>[0-9A-Fa-f]+)\s*;[ \t]*\n')
_ASSIGN = re.compile(r'(?m)^[ \t]*sp(?P<off>[0-9A-Fa-f]+)\s*=(?!=)\s*(?P<value>[^;{}\n]+);[ \t]*\n')


def _unwrap(text):
    """`text` without the parentheses that enclose all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _tidy(text):
    return re.sub(r'\s+', '', text)


def _split_offset(address):
    """(base, offset) of `BASE + N`, with any `(char *)` cast and enclosing parentheses dropped from BASE."""
    address = _unwrap(address)
    offset = 0
    plus = re.fullmatch(rf'(?P<base>.+?)\+\s*(?P<n>{_NUM})', address, re.S)
    if plus and plus['base'].count('(') == plus['base'].count(')'):
        address, offset = plus['base'], int(plus['n'], 0)
    address = _unwrap(address)
    cast = re.match(rf'\(\s*(?:{_BYTE}|void)\s*\*\s*\)', address)
    if cast:
        address = address[cast.end():]
    return _tidy(_unwrap(address)), offset


def _byte_read(value):
    """(base, offset, address text) of a byte read m2c writes, or None."""
    value = _unwrap(value)
    field = re.fullmatch(rf'M2C_FIELD\s*\(\s*(?P<base>[^,]+),\s*{_BYTE}\s*\*\s*,\s*(?P<n>{_NUM})\s*\)', value)
    if field:
        base = _split_offset(field['base'])
        offset = base[1] + int(field['n'], 0)
        return base[0], offset, f'(char *) ({field["base"].strip()}) + {field["n"]}'
    deref = re.match(rf'\*\s*\(\s*{_BYTE}\s*\*\s*\)\s*', value)
    if not deref:
        return None
    rest = value[deref.end():].strip()
    if rest.startswith('(') and close(rest, 0) != len(rest) and not re.match(rf'\(\s*{_BYTE}\s*\*\s*\)', rest):
        return None
    if not (rest.startswith('(') or re.fullmatch(rf'&?\s*{_ID}', rest)):
        return None
    base, offset = _split_offset(rest)
    return base, offset, _unwrap(rest)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    decls = {int(m['off'], 16): m for m in _DECL.finditer(clean, opening, end)}
    assigns = {}
    for m in _ASSIGN.finditer(clean, opening, end):
        assigns.setdefault(int(m['off'], 16), []).append(m)
    for first in sorted(decls):
        read = len(assigns.get(first, ())) == 1 and _byte_read(source[slice(*assigns[first][0].span('value'))])
        if not read or not re.search(rf'&\s*sp{decls[first]["off"]}\b', clean[opening:end]):  # the record escapes
            continue
        base, start, address = read
        aliases = {}
        for temp in re.finditer(rf'(?m)^[ \t]*(?P<t>{_ID})\s*=(?!=)\s*(?P<v>[^;{{}}\n]+);[ \t]*\n', clean[opening:end]):
            if _split_offset(temp['v']) == (base, start):
                aliases[temp['t']] = (opening + temp.start(), opening + temp.end())
        run = [(first, assigns[first][0])]
        for k in range(1, 8):
            off = first + k
            if off not in decls or decls[off]['type'] != decls[first]['type'] or len(assigns.get(off, ())) != 1:
                break
            found = _byte_read(source[slice(*assigns[off][0].span('value'))])
            if not found:
                break
            same = found[0] == base and found[1] == start + k
            through = found[0] in aliases and found[1] == k
            if not (same or through) or assigns[off][0].start() < run[-1][1].end():
                break
            run.append((off, assigns[off][0]))
        if len(run) < 2:
            continue
        between = clean[run[0][1].end():run[-1][1].start()]
        # nothing between the reads may write memory the copy would then see differently
        if any(not re.fullmatch(rf'\s*(?:{_ID}\s*=(?!=)[^;{{}}()]*)?', part) and not part.strip().startswith('sp')
               for part in between.split(';')):
            continue
        return _rewrite(source, clean, opening, end, decls, run, address, aliases)
    return []


def _rewrite(source, clean, opening, end, decls, run, address, aliases):
    first = run[0][0]
    whole = f'sp{first:X}'
    names = {off: decls[off]['off'] for off, _ in run}
    decl = decls[first]
    record = f'{decl["indent"]}struct {{ {decl["type"]} b[{len(run)}]; }} {whole};\n'
    indent = source[run[0][1].start():run[0][1].end()]
    indent = indent[:len(indent) - len(indent.lstrip())]
    copy = f'{indent}{whole} = *(__typeof__({whole}) *) ({address});\n'
    edits = [(decl.start(), decl.end(), record), (run[0][1].start(), run[0][1].end(), copy)]
    edits += [(decls[off].start(), decls[off].end(), '') for off, _ in run[1:]]
    edits += [(m.start(), m.end(), '') for _, m in run[1:]]
    skip = [(a, b) for a, b, _ in edits]
    for alias, (a, b) in aliases.items():
        rest = clean[opening:a] + clean[b:end]
        for _, m in run:
            rest = rest.replace(clean[m.start():m.end()], '')
        uses = re.findall(rf'\b{alias}\b', rest)
        declared = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?\**[ \t]*\b{alias}[ \t]*;[ \t]*\n', clean[opening:end])
        if declared and len(uses) == 1:
            edits.append((a, b, ''))
            edits.append((opening + declared.start(), opening + declared.end(), ''))
            skip += [(a, b), (opening + declared.start(), opening + declared.end())]
    for k, (off, _) in enumerate(run):
        word = rf'(?P<amp>&\s*)?\bsp{names[off]}\b'
        for use in re.finditer(word, clean[opening:end]):
            a, b = opening + use.start(), opening + use.end()
            if any(x <= a < y for x, y in skip):
                continue
            if use['amp'] and k == 0:
                edits.append((a, b, f'{whole}.b'))
            else:
                edits.append((a, b, f'{use["amp"] or ""}{whole}.b[{k}]'))
    text = source
    for a, b, value in sorted(edits, reverse=True):
        text = text[:a] + value + text[b:]
    return [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
