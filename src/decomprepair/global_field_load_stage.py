"""A field of a global pointer read at the start of its block, where the game read it ahead of the float stores.

m2c puts the read where its value is first used: `slot = M2C_FIELD(gState, s32 *, 0x74C) + (n << 6);` after a run of
stores to a local array. GCC 2.7.2 keeps a load where the source puts it relative to the stores it can't prove
independent (a store through a stack array and a global are independent, but the first scheduler orders by the
expansion), so the instructions of the read sit below the stores. The game's read came first: the pointer, its field
in a saved register and the stores after it. A KMC N64 function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 731 instructions) went
919 -> 619 with `base = M2C_FIELD(gState, s32 *, 0x74C);` as the first statement of the block and `slot = base +
(n << 6);` where it was. Two scheduling rows and three load rows were exact afterwards.

Offered for an assignment `lhs = M2C_FIELD(G, T *, K) + rest;` (or a plain `lhs = M2C_FIELD(G, T *, K);`) of a global
`G` (not a local or parameter) whose block has at least three statements before it, none a call or a store through a
pointer, and none assigning `G`. A candidate: the judge's byte comparison decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import lines

FAMILY = 'global_field_load_stage'
FAMILIES = (FAMILY,)
LIMIT = 6
NAME = '__repair_field_base'
FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>[^,()]+?)\s*,\s*(?P<offset>(?:0[xX][0-9A-Fa-f]+|\d+))\s*\)')
ASSIGN = re.compile(rf'^(?P<indent>[ \t]*)(?P<lhs>{IDENT})\s*=(?!=)\s*(?P<rhs>[^;{{}}]*);$')


def variants(source, name):
    part = view(source, name)
    if not part or NAME in part.clean:
        return []
    body = lines(part, source)
    declared = set(re.findall(rf'\b(?:[su](?:8|16|32)|f32|char|short|int|float|void)\s*\**\s*({IDENT})\s*(?:\[[^\]]*\])?\s*[;,]',
                              part.clean[part.opening:part.end])) | set(re.findall(rf'(?:\w+\s*\*?\s*)({IDENT})\s*[,)]', part.clean[part.clean.rfind('(', 0, part.opening):part.opening]))
    result = []
    for index, line in enumerate(body):
        hit = ASSIGN.match(line.text)
        field = FIELD.search(hit['rhs']) if hit else None
        if not field or field['base'] in declared or hit['lhs'] not in declared:
            continue
        rhs = hit['rhs']
        # the read must be the first operand (`G->f + rest`), the shape m2c writes for an address plus an offset
        if rhs[:field.start()].strip() or re.search(rf'\b{IDENT}\s*\(', rhs.replace('M2C_FIELD(', '')):
            continue
        # the block's first statement line: walk back over statements at this indentation to the block's `{`
        first = index
        while first > 0 and body[first - 1].indent == line.indent and body[first - 1].stripped and not body[first - 1].stripped.endswith('{') \
                and not body[first - 1].stripped.startswith('}') and body[first - 1].stripped.endswith(';') and '=' in body[first - 1].stripped:
            first -= 1
        if index - first < 3:
            continue
        between = ' '.join(b.text for b in body[first:index])
        if (re.search(rf'\b{IDENT}\s*\(', between.replace('M2C_FIELD(', '')) or re.search(rf'\b{re.escape(field["base"])}\b', between)
                or re.search(r'(?:^|;)\s*(?:\*|M2C_FIELD)', between)):
            continue
        temp = NAME
        read = f'{line.indent}{temp} = {rhs[field.start():field.end()]};\n'
        edits = [(body[first].start, body[first].start, read),
                 (line.start, line.end, f'{line.indent}{hit["lhs"]} = {temp}{rhs[field.end():]};\n')]
        text = edit(source, edits)
        text = re.sub(r'(\n[ \t]*\w[\w ]*\*?\s*' + re.escape(hit['lhs']) + r'\s*;\n)', r'\1' + f'    s32 {temp};\n', text, count=1)
        if f's32 {temp};' not in text:
            continue
        result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result
