"""A read wider than the stride its index is scaled by, written as an element of a table of that stride.

A draft that took a table for raw bytes can read more than one element:

    extern char steps[];                                    extern u16 steps[];
    ...                                          ->         ...
    if (pad & *(s32 *)((i * 2) + steps)) {                  if (pad & steps[i]) {

Four bytes read at a stride of two overlap the next entry, and the compiler narrows `u16 & *(s32 *)p` to a halfword
load of the *second* half on a big-endian target (`lhu $v0, 2($v0)`), so the table's element is the stride's width.
On a 132-instruction N64 input-sequence routine (SN64 GCC, `-O2 -mips3 -mfp64`, three such tables) the cast to `u16`
took its m2c start from 2988 to 2023, and the element type on the table with a plain subscript was the last step of the
chain (630 -> 0): `((u16 *)steps)[i]` on the byte table scored the same 630, since the address of a declared halfword
array is formed in another order.

`variants` takes `*(T *)((i * K) + table)` (either order of the sum, `K` 1 or 2, `T` an integer type wider than `K`,
`i` a plain name) and writes the element, unsigned first then signed. A table the source declares `extern char`,
`u8` or `s8` `table[];` whose every mention is such a read with one stride is redeclared with the element type and
subscripted; any other is subscripted through a cast. The program changes where the wide read used the neighbouring
bytes, which is the hypothesis the judge tests. Returns [(family, source)]."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stride_element_read'
FAMILIES = (FAMILY,)
_WIDTHS = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4}
_ELEMENTS = {1: ('u8', 's8'), 2: ('u16', 's16')}
_SCALED = rf'\(\s*(?P<{{0}}index>{IDENT})\s*\*\s*(?P<{{0}}stride>[12])\s*\)'
_READ = re.compile(
    rf'\*\s*\(\s*(?P<type>s32|u32|int|s16|u16|short)\s*\*\s*\)\s*\(\s*(?:'
    rf'{_SCALED.format("a")}\s*\+\s*(?P<atable>{IDENT})|(?P<btable>{IDENT})\s*\+\s*{_SCALED.format("b")})\s*\)')


def _reads(part):
    """[(start, end, table, index, stride)] for each read in the function wider than its stride."""
    found = []
    for hit in _READ.finditer(part.clean, part.opening, part.end):
        side = 'a' if hit['atable'] else 'b'
        stride = int(hit[side + 'stride'])
        before = part.clean[:hit.start()].rstrip()
        if _WIDTHS[hit['type']] <= stride or before.endswith('&') and not re.search(r'[\w)\]&]\s*&$', before):
            continue  # not wider than the stride, or the address is taken (`x & *p` is a read, `&*p` is not)
        if re.match(r'\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)', part.clean[hit.end():]):
            continue  # a store writes the neighbour: another program altogether
        found.append((hit.start(), hit.end(), hit[side + 'table'], hit[side + 'index'], stride))
    return found


def _declaration(part, table):
    """The `extern <byte type> table[];` line's type span, when the source declares the table so."""
    return re.search(rf'(?m)^[ \t]*extern[ \t]+(?P<type>(?:unsigned[ \t]+|signed[ \t]+)?char|u8|s8)[ \t]+{table}'
                     rf'[ \t]*\[[ \t]*\][ \t]*;', part.clean[:part.opening])


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    reads = _reads(part)
    if not reads:
        return []
    out = []
    for sign in (0, 1):
        edits, typed = [], {}
        for start, end, table, index, stride in reads:
            element = _ELEMENTS[stride][sign]
            declared = _declaration(part, table)
            mine = [r for r in reads if r[2] == table]
            whole = (declared and len({r[4] for r in mine}) == 1
                     and len(re.findall(rf'(?<![\w.>]){table}\b', part.clean)) == len(mine) + 1)
            if whole:
                typed[table] = (declared.start('type'), declared.end('type'), element)
                edits.append((start, end, f'{table}[{index}]'))
            else:
                edits.append((start, end, f'(({element} *){table})[{index}]'))
        text = edit(source, edits + list(typed.values()))
        if (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 200}  # registry.py
