"""A byte table m2c reads through `index + TABLE`, written as the table's own subscript.

m2c prints an indexed byte table as pointer arithmetic on the sum, with the constant part of the address as a second
displacement:

    extern char T[];                              extern u8 T[];
    a = *(u8 *)(i + T);                    ->     a = T[i];
    b = M2C_FIELD((i + T), u8 *, 1);              b = T[i + 1];

The two are one program, but gcc does not build them alike: `*((i + T) + 1)` keeps one address register for the
sum, where the subscript `T[i + 1]` rebuilds `i + T` from the index and the table's `lui/addiu` for each read
(`addu $v0,$v1,$a0; lbu 1($v0)`). An N64 effect update (`sn-n64-281 -G0 -mips3 -O2`) went 900 -> 655 with the
subscripts and, with its index local also inlined, 655 -> 0. `asm_table_index_read` writes the plain
`*(u8 *)(i + T)` read but not the `M2C_FIELD((i + T), u8 *, K)` ones beside it, which is what the target's three
neighbouring bytes are. (Hypothesis, not read in the compiler: the subscript's index is a separate address term.)

Only a table declared `extern char|s8|u8 T[];` is rewritten, only when every read of it in this form has one byte
type (`u8` or `s8`) and no other use of it would read differently with the table declared as that type. A cast of
the read to its own type goes with it. All tables together, then each alone; the exact judge decides each.
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit

FAMILY = 'table_sum_subscript'
FAMILIES = (FAMILY,)
LIMIT = 8

_IDENT = r'[A-Za-z_]\w*'
_TERM = rf'(?:{_IDENT}|\([^()]*\))'
_DECL = re.compile(rf'(?m)^[ \t]*extern[ \t]+(?P<type>char|s8|u8)[ \t]+(?P<table>{_IDENT})[ \t]*\[[ \t]*\][ \t]*;')


def _reads(table):
    """The two spellings of a read through the sum, with an optional redundant cast before it."""
    total = rf'(?:(?P<index>{_TERM})[ \t]*\+[ \t]*{table}|{table}[ \t]*\+[ \t]*(?P<other>{_TERM}))'
    cast = r'(?:\([ \t]*(?P<cast>u8|s8)[ \t]*\)[ \t]*)?'
    return (re.compile(rf'{cast}M2C_FIELD[ \t]*\([ \t]*\([ \t]*{total}[ \t]*\)[ \t]*,[ \t]*(?P<type>u8|s8)[ \t]*\*[ \t]*,'
                       rf'[ \t]*(?P<offset>0[xX][0-9A-Fa-f]+|\d+)[ \t]*\)'),
            re.compile(rf'{cast}\*[ \t]*\([ \t]*(?P<type>u8|s8)[ \t]*\*[ \t]*\)[ \t]*\([ \t]*{total}[ \t]*\)'))


def _table(clean, source, declaration, lo, hi):
    """The edits for one table, or None when it has no such read or another use would change."""
    table, declared = declaration['table'], declaration['type']
    edits, types = [], set()
    for pattern in _reads(table):
        for read in pattern.finditer(clean, lo, hi):
            kind = read['type']
            if read['cast'] and read['cast'] != kind:
                return None
            before = clean[lo:read.start()].rstrip()
            after = clean[read.end():hi].lstrip()
            if before.endswith('&') and not before.endswith('&&') or re.match(r'(?:\[|\.|->)', after):
                return None
            group = 'index' if read['index'] else 'other'
            index = source[read.start(group):read.end(group)]
            offset = read.groupdict().get('offset')
            if offset and int(offset, 0):
                index = f'{index} + {offset}'
            types.add(kind)
            edits.append((read.start(), read.end(), f'{table}[{index}]'))
    if len(types) != 1:
        return None
    kind = types.pop()
    if kind != declared:
        covered = [(start, end) for start, end, _ in edits]
        for use in re.finditer(rf'\b{table}\b', clean):
            at = use.start()
            if declaration.start() <= at < declaration.end() or any(a <= at < b for a, b in covered):
                continue
            # a value read of the table itself would now have the other signedness
            if clean[use.end():].lstrip().startswith('[') or clean[:at].rstrip().endswith('*'):
                return None
        edits.append((declaration.start('type'), declaration.end('type'), kind))
    return edits


def variants(source, name):
    span = find(source, name)
    if not span or '+' not in source:
        return []
    clean = _blank(source)
    tables = []
    for declaration in _DECL.finditer(clean):
        edits = _table(clean, source, declaration, span[0], span[1])
        if edits:
            tables.append(edits)
    picks = ([tables] if len(tables) > 1 else []) + [[one] for one in tables]
    return [(FAMILY, edit(source, [change for one in pick for change in one])) for pick in picks[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
