"""m2c's copy of a byte record with a part-word tail, written back as the record assignment.

A local record of bytes initialised from a constant whose size is not a multiple of four (`u8 counts[6] = {...};`) is a
GCC block move: `lwl`/`lwr` for each whole word, then `lb` (or `lh`) for the tail. m2c names every piece:

    temp_a3 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 0));
    sp28 = temp_a3;
    sp2C = M2C_FIELD(&D_80001000, s8 *, 4);
    sp2D = M2C_FIELD(&D_80001000, s8 *, 5);
    take(*(&sp28 + index));

`unaligned_stack_struct_copy` writes runs of two or more whole words only, so a tail or a single word stayed as it was.

unaligned_tail_struct_copy
    Statements that copy one symbol from offset 0 (whole unaligned words first, then bytes and halves) into `sp` locals
    at matching stack offsets become one assignment of a byte record of that size; the later locals' declarations go.
    Byte arithmetic on the first local's address (`&sp28 + i`) is kept in bytes with a cast. The temporary a word went
    through is dropped, or reloaded from the record when the function reads it later, so an extra argument trimmed
    afterwards leaves no load of the constant behind. Declined when a later local
    is named anywhere else, when the first is used other than by address, or when it was declared a wider type than a
    byte (other than m2c's unknown) and used in pointer arithmetic, or when the temporary is read before the copy or
    written again.

Matched an N64 asset-loading routine (SN GCC 2.8.1, `-O2`, 48 instructions) with a six-byte table of counts: after
`symbol_stack_block_copy`, `nested_guard` and `callee_arity_trim` this edit took it from 2216 to 0 (one measured
function). A hypothesis like every family's; the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'unaligned_tail_struct_copy'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_WORD = r'(?:s32|u32|int|M2C_UNK32|M2C_UNK)'
_PART = {'s8': 1, 'u8': 1, 'M2C_UNK8': 1, 's16': 2, 'u16': 2, 'M2C_UNK16': 2}
_LOAD = (rf'(?:\(\s*{_WORD}\s*\)\s*)?M2C_UNALIGNED32\(\s*M2C_FIELD\(\s*&\s*(?P<symbol>{_ID})\s*,\s*{_WORD}\s*\*\s*,'
         rf'\s*(?P<off>{_NUM})\s*\)\s*\)')
_HEAD = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:(?P<temp>{_ID})\s*=\s*(?P<load>{_LOAD})\s*;[ \t]*\n[ \t]*'
                   rf'sp(?P<via>[0-9A-F]+)\s*=\s*(?P=temp)\s*;[ \t]*\n)')
_DIRECT = re.compile(rf'(?m)^(?P<indent>[ \t]*)sp(?P<via>[0-9A-F]+)\s*=\s*(?P<load>{_LOAD})\s*;[ \t]*\n')
_TAIL = re.compile(rf'(?m)^[ \t]*sp(?P<via>[0-9A-F]+)\s*=\s*(?:\(\s*\w+\s*\)\s*)?M2C_FIELD\(\s*&\s*(?P<symbol>{_ID})\s*,'
                   rf'\s*(?P<type>{"|".join(_PART)})\s*\*\s*,\s*(?P<off>{_NUM})\s*\)\s*;[ \t]*\n')
_BYTE_TYPES = ('M2C_UNK', 'M2C_UNK32', 'M2C_UNK8', 's8', 'u8', 'char')


def _piece(clean, at, end):
    """The copy statement that starts at `at`: (match, width), or None."""
    for pattern, width in ((_HEAD, 4), (_DIRECT, 4), (_TAIL, 0)):
        found = pattern.match(clean, at, end)
        if found:
            return found, width or _PART[found['type']]
    return None


def _runs(clean, start, end):
    """Runs of copies that tile one symbol from 0 into consecutive stack bytes: whole words, then at least one part."""
    at = start
    while at < end:
        first = _piece(clean, at, end)
        if not first or first[1] != 4 or int(first[0]['off'], 0):
            line = clean.find('\n', at, end)
            at = end if line < 0 else line + 1
            continue
        run, size, parts = [first[0]], 4, 0
        base, symbol = int(first[0]['via'], 16), first[0]['symbol']
        while True:
            later = _piece(clean, run[-1].end(), end)
            if not later:
                break
            match, width = later
            if (match['symbol'] != symbol or int(match['off'], 0) != size or int(match['via'], 16) != base + size
                    or (width == 4 and parts)):
                break
            run.append(match)
            size += width
            parts += width != 4
        if parts:
            yield run, size
        at = run[-1].end()


def _declaration(clean, opening, end, name):
    found = list(re.compile(rf'(?m)^[ \t]*(?P<type>{_ID})[ \t]+{name}\s*;[ \t]*\n').finditer(clean, opening, end))
    return found[0] if len(found) == 1 else None


def _uses(clean, opening, end, name, skip):
    """The offsets in the body where `name` is written outside the spans in `skip`."""
    return [m.start() for m in re.compile(rf'\b{name}\b').finditer(clean, opening, end)
            if not any(low <= m.start() < high for low, high in skip)]


def _written(clean, opening, end, use, name):
    """Whether the use of `name` at `use` assigns it, steps it or takes its address."""
    return bool(re.compile(r'\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)').match(clean, use + len(name), end)
                or re.search(r'(?:(?<!&)&|\+\+|--)\s*$', clean[opening:use]))


def _rewrite(source, clean, opening, end, run, size):
    """The edits that write one run as a record assignment, or None."""
    locals_ = [f'sp{copy["via"]}' for copy in run]
    declared = [_declaration(clean, opening, end, local) for local in locals_]
    if not all(declared):
        return None
    copies = [copy.span() for copy in run]
    first, kind = locals_[0], declared[0]['type']
    if any(_uses(clean, opening, end, local, copies + [declared[k].span()])
           for k, local in enumerate(locals_) if k):
        return None
    edits = []
    for use in _uses(clean, opening, end, first, copies + [declared[0].span()]):
        address = re.search(r'(?<!&)&\s*$', clean[opening:use])
        if not address:
            return None
        if re.match(r'\s*(?:\+(?![+=])|-(?![-=>]))', clean[use + len(first):end]):
            if kind not in _BYTE_TYPES:
                return None
            cast = '(s8 *) ' if kind == 's8' else '(u8 *) '
            at = opening + address.start()
            edits.append((at, at, cast))
    record = f'__repair_bytes{size}'
    spare, reloads = [], []
    for position, copy in enumerate(run):
        temp = copy.groupdict().get('temp')
        if not temp:
            continue
        declaration = _declaration(clean, opening, end, temp)
        if declaration is None:
            return None
        later = _uses(clean, opening, end, temp, copies + [declaration.span()])
        if not later:
            spare.append(declaration)
            continue
        if any(use < run[-1].end() or _written(clean, opening, end, use, temp) for use in later):
            return None
        # A later read of the temporary reads the same word back out of the record.
        reloads.append(f'{run[0]["indent"]}{temp} = ((s32 *) &{first})[{position}];\n')
    record = f'__repair_bytes{size}'
    copied = f'{run[0]["indent"]}{first} = *({record} *) &{run[0]["symbol"]};\n'
    edits.append((run[0].start(), run[-1].end(), copied + ''.join(reloads)))
    head = source[declared[0].start():declared[0].end()]
    indent = head[:len(head) - len(head.lstrip(' \t'))]
    edits.append((declared[0].start(), declared[0].end(), f'{indent}{record} {first};\n'))
    edits.extend((m.start(), m.end(), '') for m in declared[1:] + spare)
    return edits


def variants(source, name):
    """One child with every such run of `name` written as a record assignment."""
    if 'M2C_UNALIGNED32(' not in source:
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    edits, sizes, claimed = [], set(), set()
    for run, size in _runs(clean, opening, end):
        words = {copy['via'] for copy in run}
        if claimed & words:
            continue
        found = _rewrite(source, clean, opening, end, run, size)
        if found is None:
            continue
        claimed |= words
        sizes.add(size)
        edits.extend(found)
    if not edits:
        return []
    text = source
    for start, stop, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[stop:]
    typedefs = ''.join(f'typedef struct {{ char data[{n}]; }} __repair_bytes{n};\n'
                       for n in sorted(sizes) if f'__repair_bytes{n};' not in source)
    at = source.rfind('\n', 0, span[0]) + 1
    return [(FAMILY, text[:at] + typedefs + text[at:])]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
