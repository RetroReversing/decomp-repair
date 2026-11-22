"""A table element read in an `if` after a run of stores: its address in a pointer local ahead of the fence, its value
read after the first store.

m2c writes `D_A = 0; D_B = 1; if (Table[slot] != 0) { ... }` and the compiler schedules the block's insns in the order
its priorities give: the index shift ends up after the stores, and the element's load in the stall after the address
instead of in front of the second store. The target has the shift ahead of the first store (the loop-begin note of the
`do { } while (0)` fence the saved source carries makes everything after it depend on the stores before it, so the
shift has to be computed outside it) and the load between the two stores (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32
-O2`, a 136-instruction menu reset: 60 -> 0). Each of the two edits alone scores worse (370 with only the pointer
hoisted: the load then follows both stores and fills no delay slot), so the family writes them as one child:

    { T *elem_p = &Table[slot]; T elem_v;
      do { D_A = 0; elem_v = *elem_p; D_B = 1; if (elem_v != 0) { ... } ... } while (0); }

with the value read after the first, second or third store (or just before the `if`), and the address alone as a
child of its own. A hypothesis for why (sched.c: the note makes the first insn after it depend on all the earlier ones);
only the measured score is established. The exact judge decides.

The shape: `if (Table[slot])`, `if (!Table[slot])` or `if (Table[slot] != 0)` / `== 0` where `Table` is an array
declared above the function (not volatile) and `slot` a plain name or number, after one or more statements of the same
block that are plain `name = value;` stores to other names (so none can write the element or change the index), with
no brace, label or goto between. When the block is a `do { } while (0)` the scope goes round the whole statement,
otherwise at the head of the block.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'element_read_stage'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
CONDITION = re.compile(rf'\bif\s*\(\s*(?P<not>!\s*)?(?P<elem>(?P<table>{IDENT})\s*\[\s*(?P<index>{IDENT}|0[xX][0-9a-fA-F]+|\d+)\s*\])'
                       r'\s*(?P<cmp>(?:!=|==)\s*0)?\s*\)')
STORE = re.compile(rf'\s*(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[-+~\w\s.]+?)\s*;')


def _element_type(source, part, table):
    for hit in re.finditer(rf'(?m)^[ \t]*(?:extern\s+|static\s+)*(?P<type>[A-Za-z_][\w\s]*?)\s+{re.escape(table)}\s*\[[^\]]*\]\s*(?:;|=)',
                           source[:part.opening]):
        text = hit['type'].strip()
        if 'volatile' in text or not text:
            return None
        return text
    return None


def _enclosing(clean, part, position):
    depth = 0
    for index in range(position - 1, part.opening - 1, -1):
        char = clean[index]
        if char == '}':
            depth += 1
        elif char == '{':
            if depth == 0:
                return index
            depth -= 1
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in CONDITION.finditer(clean, part.opening, part.end):
        table, index = hit['table'], hit['index']
        opening = _enclosing(clean, part, hit.start())
        if opening is None or opening == part.opening:
            continue
        kind = _element_type(source, part, table)
        if not kind or re.search(rf'\bvolatile\b[^;]*\b{re.escape(index)}\b', source[:part.opening]):
            continue
        stretch = clean[opening + 1:hit.start()]
        if re.search(r'[{}:]|\bgoto\b|\breturn\b', stretch) or not stretch.strip():
            continue
        stores, position = [], 0
        while position < len(stretch) and (m := STORE.match(stretch, position)):
            if m['name'] in (table, index) or re.search(rf'\b{re.escape(index)}\b|\b{re.escape(table)}\b', m['value']):
                break
            stores.append(opening + 1 + m.end())
            position = m.end()
        if not stores or stretch[position:].strip():
            continue
        head = clean[:opening].rstrip()
        fence = re.search(r'\bdo$', head)
        if fence:
            block_end = close(clean, opening, '{', '}')
            tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', clean[block_end:]) if block_end else None
            if not tail:
                continue
            scope_start, scope_end = fence.start(), block_end + tail.end()
        else:
            scope_start = scope_end = None
        ptr, val = 'elem_p', 'elem_v'
        while re.search(rf'\b{ptr}\b', clean):
            ptr += '_'
        while re.search(rf'\b{val}\b', clean):
            val += '_'
        declaration = f'{kind} *{ptr} = &{table}[{index}];'
        reads = [None] + stores[:3] + [hit.start()]  # None: the address alone
        for stage in reads:
            edits = []
            if stage is None:
                replacement, extra = f'*{ptr}', ''
                value = ''
            else:
                replacement, extra, value = val, f' {val} = *{ptr};', f' {kind} {val};'
            if fence:
                edits.append((scope_start, scope_start, f'{{ {declaration}{value} '))
                edits.append((scope_end, scope_end, ' }'))
            else:
                edits.append((opening + 1, opening + 1, f' {declaration}{value}'))
            if stage is not None:
                edits.append((stage, stage, extra if stage != hit.start() else extra + ' '))
            edits.append((hit.start('elem'), hit.end('elem'), replacement))
            out.append((FAMILY, edit(source, edits)))
            if len(out) >= LIMIT:
                return list(dict.fromkeys(out))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 50}  # the registry: no caller wiring (registry.py)
