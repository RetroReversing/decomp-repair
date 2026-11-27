"""Two or more block copies into m2c's scratch frame array, written as the local records the game copied into.

A function that starts by copying a table to a local (`Table ids = gTable;`) comes back from m2c as one `u8 sp[N]` the
size of the frame, a `#define` per slot, and the compiler's copy loop through two cursors:

    u8 sp[296];                                              __repair_block90w __repair_stack10;
    #define sp10 ((s32 *)(sp + 0x10))                        __repair_block78w __repair_stackA0;
    #define spA4 (*(s32 *)(sp + 0xA4))
    var_v1 = &sp10[0]; var_v0 = gFirst;                ->    __repair_stack10 = *(__repair_block90w *)(gFirst);
    do { ... } while (var_v0 != (gFirst + 0x90));            __repair_stackA0 = *(__repair_block78w *)(gSecond);
    ... the second copy ...
    spA4 = 0x13A;                                            __repair_stackA0.data[1] = 0x13A;

Neither half helps alone: with the loops written as assignments the scratch array still sizes the frame, and the copy
loops are what the compiler makes of a record assignment. So the child does both: every copy becomes an assignment
(`block_move_struct_assign`), every record the copies fill becomes a local of its own, declared in the order of the
target's offsets, and every slot that falls inside one is spelled as its element. Offered when each use of `sp` is a
slot macro inside one of the copied records, and the records don't overlap.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 function (164 instructions) that copies two id tables to its frame
(0x90 and 0x78 bytes) and queues one page of one of them: the raw draft scored 7788, this step alone 3698, and
`guarded_masked_counter_for` and `asm_member_view` are the next two of the chain. The stack's layout following the
declaration order is a hypothesis; the judge decides.
"""
import re

from . import block_move_struct_assign
from .csource import _blank, find

FAMILY = 'scratch_frame_records'
FAMILIES = (FAMILY,)

_SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4}
_ARRAY = re.compile(r'(?m)^[ \t]*(?:u8|s8|char|unsigned char)\s+sp\s*\[\s*(?:0[xX][0-9A-Fa-f]+|\d+)\s*\]\s*;[ \t]*\n')
_SLOT = re.compile(
    r'(?m)^#define[ \t]+(?P<name>\w+)[ \t]+\((?P<value>\*)?\((?P<type>\w+)[ \t]*\*\)[ \t]*\(sp[ \t]*\+[ \t]*'
    r'(?P<at>0[xX][0-9A-Fa-f]+|\d+)\)\)[ \t]*\n')
_COPY = re.compile(
    r'(?m)^(?P<indent>[ \t]*)\*\((?P<record>__repair_block(?P<size>[0-9A-F]+)w?) \*\)\((?P<dest>[^;\n]*?)\) = '
    r'\*\((?P=record) \*\)\((?P<src>[^;\n]*)\);\n')


def _copies(source, name):
    """`source` with every block move written as an assignment (word records where both are offered)."""
    for _ in range(8):
        children = block_move_struct_assign.variants(source, name)
        if not children:
            break
        words = [text for _, text in children if re.search(r'__repair_block[0-9A-F]+w \*', text)]
        source = words[0] if words else children[0][1]
    return source


def variants(source, name):
    if not _ARRAY.search(source) or not find(source, name):
        return []
    text = _copies(source, name)
    span = find(text, name)
    if not span:
        return []
    slots = {m['name']: (int(m['at'], 0), m['type'], bool(m['value'])) for m in _SLOT.finditer(text)}
    if any(kind not in _SIZES for _, kind, _value in slots.values()):
        return []
    records = {}
    for copy in _COPY.finditer(text, *span):
        slot = re.fullmatch(r'&?\(?\s*(?P<name>\w+)(?:\s*\[\s*0\s*\])?\s*\)?', copy['dest'].strip())
        if not slot or slot['name'] not in slots:
            return []
        at = slots[slot['name']][0]
        if at in records:
            return []
        records[at] = (int(copy['size'], 16), copy['record'], copy)
    ordered = sorted(records)
    if len(ordered) < 1 or any(a + records[a][0] > b for a, b in zip(ordered, ordered[1:])):
        return []

    def owner(at, size):
        return next((start for start in ordered if start <= at and at + size <= start + records[start][0]), None)

    head, body = text[:span[0]], text[span[0]:span[1]]
    tail = text[span[1]:]
    declaration = _ARRAY.search(body)
    if not declaration:
        return []
    indent = re.match(r'[ \t]*', declaration.group())[0]
    locals_ = ''.join(f'{indent}{records[start][1]} __repair_stack{start:X};\n' for start in ordered)
    body = body[:declaration.start()] + locals_ + body[declaration.end():]
    body = _COPY.sub(lambda m: next(
        f'{m["indent"]}__repair_stack{start:X} = *({records[start][1]} *)({m["src"]});\n'
        for start in ordered if records[start][2]['src'] == m['src']), body)
    for slot, (at, kind, value) in sorted(slots.items(), key=lambda item: -len(item[0])):
        if not re.search(rf'\b{slot}\b', _blank(body)):
            continue
        size = _SIZES[kind]
        start = owner(at, size)
        if start is None:
            return []
        record = records[start][1]
        offset = at - start
        word = record.endswith('w') and size == 4 and kind != 'f32' and offset % 4 == 0
        if word:
            element = f'__repair_stack{start:X}.data[{offset // 4}]'
            pointer = f'__repair_stack{start:X}.data' if not offset else f'(&{element})'
        else:
            pointer = f'(({kind} *)((u8 *)&__repair_stack{start:X} + 0x{offset:X}))'
            element = f'(*{pointer})'
        body = re.sub(rf'\b{slot}\b', element if value else pointer, body)
    if re.search(r'\bsp\b', _blank(body)):
        return []
    # `(&record.data[0])[i]` is the record's own element: through the address, SN GCC hoists it out of a loop
    body = re.sub(r'\(&(__repair_stack\w+\.data)\[0\]\)(?=\s*\[)', r'\1', body)
    head = _SLOT.sub('', head)
    result = head + body + tail
    return [(FAMILY, result)] if result != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
