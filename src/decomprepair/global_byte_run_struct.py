"""Consecutive byte or halfword globals copied one by one into locals, as the struct copy the game made.

`color = gColor;` of a three-byte colour record takes the global's address once and moves `lb 0/1/2` into three
registers before the three `sb`s. m2c writes one scalar per byte,

    sp18 = D_800038E4;
    sp19 = D_800038E5;
    sp1A = D_800038E6;
    draw(&sp18);

which loads and stores each byte in turn, each through its own address. When two to eight such globals have
consecutive addresses, are copied in order into locals of one type, and only the first local is used again (by
address), they are written as one record assigned whole. An N64 function (SN GCC 2.8.1) went 3665 -> 1355 with this
edit alone, and was exact with the rest of its edits.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_byte_run_struct'
FAMILIES = (FAMILY,)

_TYPES = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1,
          's16': 2, 'u16': 2, 'short': 2, 'signed short': 2, 'unsigned short': 2}
_TYPE = r'(?:(?:signed|unsigned)\s+)?(?:char|short)|[su](?:8|16)'
_COPY = re.compile(rf'(?<![\w.>])(?P<local>{IDENT})\s*=\s*(?P<symbol>D_(?P<address>[0-9A-Fa-f]{{8}}))\s*;')


def _declaration(clean, begin, end, name, prefix=''):
    found = list(re.finditer(rf'(?m)^[ \t]*{prefix}(?P<type>{_TYPE})[ \t]+{name}[ \t]*;[ \t]*\n?', clean[begin:end]))
    if len(found) != 1:
        return None
    hit = found[0]
    return (begin + hit.start(), begin + hit.end(), ' '.join(hit['type'].split()),
            begin + hit.start('type'), begin + hit.end('type'))


def _runs(clean, opening, end):
    """Adjacent copy statements from consecutive addresses."""
    run = []
    for hit in _COPY.finditer(clean, opening, end):
        if run and not clean[run[-1].end():hit.start()].strip():
            run.append(hit)
            continue
        if len(run) > 1:
            yield run
        run = [hit]
    if len(run) > 1:
        yield run


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for run in _runs(clean, part.opening, part.end):
        if len(run) > 8:
            continue
        locals_ = [_declaration(clean, part.opening, part.end, hit['local']) for hit in run]
        externs = [_declaration(clean, 0, part.opening, hit['symbol'], r'extern[ \t]+') for hit in run]
        if not all(locals_) or not all(externs):
            continue
        kind = locals_[0][2]
        size = _TYPES.get(kind)
        addresses = [int(hit['address'], 16) for hit in run]
        if (not size or any(d[2] != kind for d in locals_) or any(_TYPES.get(d[2]) != size for d in externs)
                or addresses != [addresses[0] + i * size for i in range(len(run))]):
            continue
        body = clean[part.opening:part.end]
        # every other global is read only by its copy, every other local only declared and assigned, and the first
        # local is only assigned here and then named by address
        if any(len(re.findall(rf'\b{hit["symbol"]}\b', body)) != 1 for hit in run):
            continue
        if any(len(re.findall(rf'\b{hit["local"]}\b', body)) != 2 for hit in run[1:]):
            continue
        first = run[0]['local']
        if len(re.findall(rf'\b{first}\b', body)) != 2 + len(re.findall(rf'(?<!&)&\s*{first}\b(?!\s*\[)', body)):
            continue
        record = f'__repair_run{len(run)}'
        while re.search(rf'\b{record}\b', clean):
            record += 'b'
        members = ' '.join(f'{kind} f{i};' for i in range(len(run)))
        extern = externs[0]
        edits = [(extern[0], extern[0], f'typedef struct {{ {members} }} {record};\n'),
                 (extern[3], extern[4], record),
                 (locals_[0][3], locals_[0][4], record),
                 (run[0].start(), run[-1].end(), f'{first} = {run[0]["symbol"]};')]
        edits += [(d[0], d[1], '') for d in locals_[1:]]
        result.append((FAMILY, edit(source, edits)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
