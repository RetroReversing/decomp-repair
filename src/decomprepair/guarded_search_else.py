"""m2c's table search whose found body sits in the guard's `else` arm, written as the `while` loop the game had.

GCC rotates `while (table[i] != key) { if (table[i] == END) return; i++; } body` into a first test, a loop and the
body after it, and m2c reads that back with the body in the first test's `else` arm, entered from the loop by a goto,
and the index kept twice (the counter and its masked copy):

    i = 0;
    if (table[0] != key) {
        v = 0 & 0xFFFF;
    loop_11:
        if (table[v] != END) {
            i += 1;
            v = i & 0xFFFF;
            if (table[i & 0xFFFF] == key) {
                goto block_13;
            }
            goto loop_11;
        }
    } else {
    block_13:
        body...
    }

No spelling of the labels gives the loop's registers back, and each half alone (the loop, the narrow index) scores
no better; the child does both:

    u16 i;
    ...
    while (table[i] != key) {
        if (table[i] == END) {
            return;
        }
        i += 1;
    }
    body...

Offered only in a `void` function where nothing but closing braces follows the `else` arm, so leaving the search
by `return` goes where the draft went. The mask (0xFFFF or 0xFF) decides the index's type.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 routine (230 instructions) that looks an id up in a local copy of
a table. From its raw m2c draft: `slot_scalar_records` 17193 -> 6860, `call_into_arms` 1980, this step 1200,
`shared_value_inline` 480, `linear_subscript_view` 0.

guarded_search_else_loop
    The block above becomes the `while` loop and the body. Where the target also shows that the calls in the body
    pass stray arguments (the index and the table m2c still saw in registers; `target_call_arity`), a second child
    drops them too: on the routine above the loop alone went 1280 -> 4590, and 410 with the arguments dropped.
"""
import re

from . import target_call_arity_repairs
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'guarded_search_else_loop'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_VALUE = r'(?:-?(?:0[xX][0-9A-Fa-f]+|\d+)|[A-Za-z_]\w*)'
_HEAD = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<array>[^\n;{{}}]+?)\[0\]\s*!=\s*(?P<key>{_VALUE})\s*\)\s*\{{\s*\n'
    rf'\s*(?P<copy>{_ID})\s*=\s*0\s*&\s*(?P<mask>0x[Ff]+)\s*;\s*\n'
    rf'\s*(?P<loop>{_ID}):\s*\n'
    rf'\s*if\s*\(\s*(?P=array)\[(?P=copy)\]\s*!=\s*(?P<end>{_VALUE})\s*\)\s*\{{\s*\n'
    rf'\s*(?P<index>{_ID})\s*\+=\s*1\s*;\s*\n'
    rf'\s*(?P=copy)\s*=\s*(?P=index)\s*&\s*(?P=mask)\s*;\s*\n'
    rf'\s*if\s*\(\s*(?P=array)\[(?:(?P=index)\s*&\s*(?P=mask)|(?P=copy))\]\s*==\s*(?P=key)\s*\)\s*\{{\s*\n'
    rf'\s*goto\s+(?P<found>{_ID})\s*;\s*\n'
    rf'\s*\}}\s*\n'
    rf'\s*goto\s+(?P=loop)\s*;\s*\n'
    rf'\s*\}}\s*\n'
    rf'\s*\}}\s*else\s*\{{\s*\n'
    rf'(?P=found):[ \t]*\n')
_TYPES = {0xFF: 'u8', 0xFFFF: 'u16'}


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', source[span[0]:span[1]]):
        return []
    clean = _blank(source)
    head = _HEAD.search(clean, span[0], span[1])
    if not head:
        return []
    kind = _TYPES.get(int(head['mask'], 16))
    index, copy = head['index'], head['copy']
    opening = clean.rfind('{', head.start(), head.end())
    closing = close(clean, opening, '{', '}')
    if not kind or not closing or not re.fullmatch(r'[\s}]*', clean[closing:span[1]]):
        return []
    body_start = clean.find('{', span[0])
    outside = clean[body_start:head.start()] + clean[head.end():span[1]]
    starts = re.findall(rf'(?m)^[ \t]*{index}\s*=\s*0\s*;', clean[body_start:head.start()])
    declared = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:s32|u32|int|s16|u16|u8)\s+{index}\s*;')
    if (not starts or not declared.search(source, body_start, head.start())
            or re.search(rf'\b{copy}\b(?!\s*;)', outside)
            or any(re.search(rf'\b{label}\b', outside) for label in (head['loop'], head['found']))):
        return []
    indent = head['indent']
    step = indent + '    '
    array, key, end = (source[head.start(g):head.end(g)] for g in ('array', 'key', 'end'))
    loop = (f'{indent}while ({array}[{index}] != {key}) {{\n'
            f'{step}if ({array}[{index}] == {end}) {{\n{step}    return;\n{step}}}\n'
            f'{step}{index} += 1;\n{indent}}}\n')
    found = source[head.end():closing - 1].rstrip() + '\n'
    text = source[:head.start()] + loop + found + source[closing:].lstrip(' \t').removeprefix('\n')
    start, stop = find(text, name)
    body = text[start:stop]
    body = declared.sub(lambda m: f'{m["indent"]}{kind} {index};', body, count=1)
    body = re.sub(rf'(?m)^[ \t]*(?:s32|u32|int|s16|u16|u8)\s+{copy}\s*;[ \t]*\n', '', body)
    body = re.sub(rf'\(\s*{index}\s*&\s*{head["mask"]}\s*\)', index, body)
    body = re.sub(rf'\b{index}\s*&\s*{head["mask"]}\b', index, body)
    result = text[:start] + body + text[stop:]
    children = [(FAMILY, result)]
    if asm:
        for _, trimmed in target_call_arity_repairs.variants(result, name, asm)[:1]:
            children.append((FAMILY, trimmed))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
