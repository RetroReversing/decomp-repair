"""A wider local copied from a byte (or halfword) value, and the copy's reads moved to a local of that narrow type.

m2c names a byte it loaded (`kind = save->kind;`), copies it into a counter-like scratch (`temp = kind;`) and reads the
scratch in the compare that follows (`if (temp == 2)`), in the other arm's index (`D_8011F15C[temp]`), then reuses the
same scratch as a loop counter in the first arm (`temp = 0;`). In KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) the
target kept the byte in its own saved register and the copy in an argument register that the compare reads
(`lbu $s2, 0x12($a0); move $a1, $s2; bne $a1, $v0, ...`). With both locals `s32` cse treats the copy as the byte's
quantity (`cse.c`, `make_regs_eqv`: the register that lives longer becomes the canonical one) and rewrites every read of
the copy to the byte's register, so the copy disappears, the byte's register collects every reference and outranks the
parameter for the first saved register (`global.c`: priority from refs and live length), and every saved register after
it is exchanged (25 rows of registers in a 154-instruction save-slot function).

A copy kept in a local of the byte's own type is a different pseudo of a different machine mode: the copy is
`(set (reg:HI) (subreg:HI (reg:SI)))` and its reads are `(zero_extend:SI (reg:HI))`, which cse (`insert_regs`: a register
of the wrong mode for the quantity is not made equivalent) leaves alone. Combine later turns the zero extension of a
value it knows is already zero-extended into a plain `move` (hypothesis: the dump shows the extension gone and the
target has a plain move; `combine.c`'s `nonzero_bits` was not read through). The width does not matter (a `u8`, a
`u16` and an `s16` copy gave the same bytes); the family uses the type the byte was read as, so the program is the same.

`narrow_copy_web` renames one assignment web: the copy `T = K;` (K a plain local that is assigned once, from a member
whose declared type is `u8`/`s8`/`u16`/`s16` everywhere in the source, from a cast to such a type, or is itself declared
so) and every read of `T` that the copy reaches before another assignment of `T`, to a new local of that type. Only a
`T` with at least one other plain assignment (a second web) is split, only reads that no other assignment of `T` can
reach are renamed, and a read that is also a write (`T++`, `T += ...`) or any `goto`, label, `volatile`, `asm` or address
taken leaves the function alone, so the program is the same program.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, locals_for, view
from .local_flow import Flow

FAMILY = 'narrow_copy_web'
FAMILIES = (FAMILY,)
NARROW = ('u8', 's8', 'u16', 's16')
CAST = {'u8': 'u8', 's8': 's8', 'u16': 'u16', 's16': 's16',
        'unsigned char': 'u8', 'signed char': 's8', 'unsigned short': 'u16', 'signed short': 's16'}
MASKS = {'0xFF': 'u8', '0xff': 'u8', '255': 'u8', '0xFFFF': 'u16', '0xffff': 'u16', '65535': 'u16'}


def _member_type(source, field):
    """The narrow type every declaration of the member `field` has in the source, or None."""
    kinds = set(re.findall(rf'\b((?:unsigned|signed)\s+(?:char|short)|[su](?:8|16|32)|int|long|char|short|f32|f64)'
                           rf'\s+{re.escape(field)}\s*(?:\[[^\]]*\])?\s*;', source))
    kinds = {CAST.get(re.sub(r'\s+', ' ', kind), kind) for kind in kinds}
    return kinds.pop() if len(kinds) == 1 and next(iter(kinds)) in NARROW else None


def _narrow_source(source, clean, body_start, body_end, decl):
    """The narrow type of the value local `decl` always holds, or None when that is not shown by the text."""
    if decl['type'] in NARROW:
        return decl['type']
    name = decl['name']
    sets = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)([^;]*);', clean[body_start:body_end])]
    others = re.findall(rf'(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)|(?:\+\+|--)\s*{re.escape(name)}\b',
                        clean[body_start:body_end])
    if len(sets) != 1 or others:
        return None
    value = sets[0][1].strip()
    cast = re.fullmatch(r'\(\s*(unsigned char|signed char|unsigned short|signed short|[su]8|[su]16)\s*\)\s*(.+)', value, re.S)
    if cast:
        return CAST[cast[1]]
    mask = re.fullmatch(rf'(.+?)\s*&\s*({NUMBER_MASK})', value, re.S)
    if mask and '|' not in mask[1]:
        return MASKS.get(mask[2])
    member = re.fullmatch(rf'[\w\s\[\]*().+-]*?(?:->|\.)\s*({IDENT})', value, re.S)
    if member and '(' not in value.replace('(*', ''):
        return _member_type(source, member[1])
    return None


NUMBER_MASK = '|'.join(re.escape(k) for k in MASKS)


def _reachable(flow, start_nodes, name):
    """Nodes a value of `name` assigned at `start_nodes` can still be read in, stopping at the next plain assignment."""
    seen, stack, reads = set(), list(start_nodes), set()
    while stack:
        index = stack.pop()
        if index in seen:
            continue
        seen.add(index)
        node = flow.nodes[index]
        if name in node.uses:
            reads.add(index)
        if name in node.defines and name not in node.uses:
            continue
        if name in node.defines:  # a read-modify-write: it extends the web, which is not split
            reads.add(index)
        stack.extend(node.successors)
    return reads


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    try:
        flow = Flow(part)
    except ValueError:
        return []
    clean, body_start, body_end = part.clean, part.opening + 1, part.end - 1
    decls = {d['name']: d for d in locals_for(part)}
    result = []
    outside = source[:part.opening] + source[part.end:]  # members are declared outside the function, locals inside
    for copy in re.finditer(rf'(?<![\w.>])({IDENT})\s*=\s*({IDENT})\s*;', clean[body_start:body_end]):
        wide, byte = copy[1], copy[2]
        if wide not in decls or byte not in decls or wide == byte:
            continue
        if decls[wide]['type'] in NARROW or _address_taken(part.body, wide):
            continue
        narrow = _narrow_source(outside, clean, body_start, body_end, decls[byte])
        if not narrow:
            continue
        at = body_start + copy.start()
        copy_nodes = [i for i, n in enumerate(flow.nodes) if n.start <= at < n.end and wide in n.defines]
        if not copy_nodes:
            continue
        other_defs = [i for i, n in enumerate(flow.nodes) if wide in n.defines and i not in copy_nodes
                      and re.match(rf'\s*{re.escape(wide)}\s*=(?!=)', clean[n.start:n.end])]
        if not other_defs:
            continue
        web = set()
        for index in copy_nodes:
            web |= _reachable(flow, flow.nodes[index].successors, wide)
        if not web:
            continue
        rest = set()
        for index in other_defs:
            rest |= _reachable(flow, flow.nodes[index].successors, wide)
        if web & rest:
            continue
        write = rf'(?:\+\+|--)\s*{re.escape(wide)}\b|(?<![\w.>]){re.escape(wide)}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=|=(?!=))'
        if any(re.search(write, clean[flow.nodes[i].start:flow.nodes[i].end]) for i in web):
            continue
        fresh = f'{wide}_{byte}'
        if re.search(rf'\b{re.escape(fresh)}\b', source):
            continue
        edits = [(body_start + copy.start(1), body_start + copy.end(1), fresh)]
        for index in sorted(web):
            node = flow.nodes[index]
            for hit in re.finditer(rf'(?<![\w.>]){re.escape(wide)}\b', clean[node.start:node.end]):
                edits.append((node.start + hit.start(), node.start + hit.end(), fresh))
        declaration = decls[wide]
        edits.append((declaration.end(), declaration.end(), f'\n  {narrow} {fresh};'))
        result.append((FAMILY, edit(source, edits)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
