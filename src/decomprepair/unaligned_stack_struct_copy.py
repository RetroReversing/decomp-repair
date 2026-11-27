"""m2c's unaligned word copies into separate stack words, written as the struct assignment they were.

A game that starts a local from a constant name, `GameName name = sName;` with `typedef struct { char c[16]; }
GameName;`, gets `lwl`/`lwr` and `swl`/`swr` from GCC: a record of bytes has alignment 1. m2c has no record, so it
declares one 4-byte local per word and copies each with its unaligned macro, and the call that takes the name's
address gets the first of them:

    M2C_UNK sp118;
    M2C_UNK sp11C;
    ...
    sp118 = M2C_UNALIGNED32(M2C_FIELD(&D_800017D0, M2C_UNK *, 0));
    sp11C = M2C_UNALIGNED32(M2C_FIELD(&D_800017D0, M2C_UNK *, 4));
    ...
    find(&sp118);

Separate words never give the block move back (three words loaded and stored, then the fourth), and the locals can
land apart. As one byte record, `sp118 = *(__repair_bytes16 *) &D_800017D0;`, they do.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 save-file check (74 instructions): the raw m2c draft went from
4885 to 839 with this alone, and `nested_guard`, `stack_gap_padding` and `stack_object_extent` then reached 0.

unaligned_stack_struct_copy
    Two or more consecutive statements that copy words at consecutive offsets of one source into `sp` locals at
    consecutive stack offsets become one assignment to the first of them, retyped as a byte record of the copied
    size; the other locals' declarations go. Every such run is rewritten in one child. Declined for a run whose later
    words the function names anywhere else, or whose first word it uses other than by address: those reads would be
    lost.

A hypothesis like every family's; the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'unaligned_stack_struct_copy'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_WORD = r'(?:s32|u32|int|M2C_UNK|M2C_UNK32)'
_COPY = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<dest>sp[0-9A-F]+)\s*=\s*(?:\(\s*{_WORD}\s*\)\s*)?M2C_UNALIGNED32\(\s*'
    rf'M2C_FIELD\(\s*(?P<base>&?\s*{_ID})\s*,\s*{_WORD}\s*\*\s*,\s*(?P<off>{_NUM})\s*\)\s*\)\s*;[ \t]*\n')


def _runs(body_start, end, clean):
    copies = list(_COPY.finditer(clean, body_start, end))
    k = 0
    while k < len(copies):
        run = [copies[k]]
        for later in copies[k + 1:]:
            n = len(run)
            if (later.start() != run[-1].end() or later['base'] != run[0]['base']
                    or int(later['off'], 0) != int(run[0]['off'], 0) + 4 * n
                    or int(later['dest'][2:], 16) != int(run[0]['dest'][2:], 16) + 4 * n):
                break
            run.append(later)
        if len(run) >= 2:
            yield run
        k += len(run)


def _declarations(clean, opening, end, run):
    """The declaration of each destination, or None when the run's locals are used in a way a record would break."""
    found = []
    for position, copy in enumerate(run):
        dest = copy['dest']
        declared = list(re.finditer(rf'(?m)^[ \t]*{_WORD}[ \t]+{dest}\s*;[ \t]*\n', clean[:end]))
        declared = [m for m in declared if m.start() > opening]
        if len(declared) != 1:
            return None
        for use in re.finditer(rf'\b{dest}\b', clean[opening:end]):
            at = opening + use.start()
            if declared[0].start() <= at < declared[0].end() or copy.start() <= at < copy.end():
                continue
            if position or not re.search(r'(?<!&)&\s*$', clean[opening:at]):
                return None
        found.append(declared[0])
    return found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    edits, sizes = [], set()
    for run in _runs(opening, end, clean):
        declared = _declarations(clean, opening, end, run)
        if declared is None:
            continue
        first, size = run[0], 4 * len(run)
        sizes.add(size)
        record = f'__repair_bytes{size}'
        base, offset = first['base'], int(first['off'], 0)
        pointer = f'((char *) {base} + 0x{offset:X})' if offset else base
        line = f'{first["indent"]}{first["dest"]} = *({record} *) {pointer};\n'
        edits.append((first.start(), run[-1].end(), line))
        head = declared[0]
        indent = source[head.start():head.end()]
        indent = indent[:len(indent) - len(indent.lstrip(' \t'))]
        edits.append((head.start(), head.end(), f'{indent}{record} {first["dest"]};\n'))
        edits.extend((m.start(), m.end(), '') for m in declared[1:])
    if not edits:
        return []
    text = source
    for start, stop, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[stop:]
    typedefs = ''.join(f'typedef struct {{ char data[{n}]; }} __repair_bytes{n};\n'
                       for n in sorted(sizes) if f'__repair_bytes{n};' not in source)
    at = source.rfind('\n', 0, span[0]) + 1
    return [(FAMILY, text[:at] + typedefs + text[at:])]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
