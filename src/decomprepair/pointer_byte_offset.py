"""A word pointer stepped by a byte count, written as the byte step it is.

m2c reads `addiu $a0, $a0, -0xC0` on an `s32 *` as `base - 0xC0`, and C scales that by the element size: the compiler
then adds -0x300. The target's constant is the byte count, so the source wants the pointer cast through bytes.

    var_a0 = base - 0xC0;           ->     var_a0 = (s32 *) ((s8 *) base - 0xC0);

On a KMC GCC 2.7.2 `-O1` N64 function (150 points once the callee's fifth argument was in) the byte step was the last
difference. Nothing else is guessed: the pointer must be declared in the function (a local or a parameter) as a pointer
to a type wider than a byte, and the offset a literal.

pointer_byte_offset
    `P + N` or `P - N` (P a declared pointer to a 2-, 4- or 8-byte type, N a literal) standing as a whole right-hand
    side or call argument becomes `(T *) ((s8 *) P +/- N)`. One child per site and one with every site. The judge
    decides each child."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'pointer_byte_offset'
FAMILIES = (FAMILY,)
LIMIT = 8
WIDE = r'(?:s16|u16|s32|u32|s64|u64|f32|f64|float|double|short|int|long|unsigned\s+(?:short|int|long))'
POINTER = re.compile(rf'(?<![\w.])(?P<type>{WIDE})\s*\*\s*(?P<name>{IDENT})\s*(?=[;=,)\[])')
SITE = re.compile(rf'(?<![\w.>*&])(?P<p>{IDENT})\s*(?P<op>[-+])\s*(?P<n>{NUMBER})(?![\w.(\[])')
BEFORE = re.compile(r'(?:[(,=]|\breturn)\s*$')
AFTER = re.compile(r'\s*(?:[,;)])')


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    head = part.clean[:part.opening]
    signature = head[head.rfind(name):]
    pointers = {}
    for scope in (signature, part.clean[part.opening:part.end]):
        for hit in POINTER.finditer(scope):
            pointers.setdefault(hit['name'], set()).add(' '.join(hit['type'].split()))
    pointers = {key: next(iter(types)) for key, types in pointers.items() if len(types) == 1}
    edits = []
    for hit in SITE.finditer(part.clean, part.opening + 1, part.end - 1):
        kind = pointers.get(hit['p'])
        if not kind or not BEFORE.search(part.clean[:hit.start()]) or not AFTER.match(part.clean, hit.end()):
            continue
        if re.search(r'(?<![\w])(?:s8|u8|char)\s*\*', part.clean[hit.start() - 12:hit.start()]):
            continue
        edits.append((hit.start(), hit.end(), f"({kind} *) ((s8 *) {hit['p']} {hit['op']} {hit['n']})"))
    edits = edits[:LIMIT]
    if not edits:
        return []
    out = [edit(source, [one]) for one in edits]
    if len(edits) > 1:
        out.append(edit(source, edits))
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
