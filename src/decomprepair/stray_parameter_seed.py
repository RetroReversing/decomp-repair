"""m2c's parameter that only seeds a local the function sets itself: no parameter at all.

A value first written inside a loop and read after it has, to m2c, a path on which nothing set it, so the register it
lives in becomes an incoming argument:

    s32 f(s32 arg0, s32 arg1) {                    s32 f(void) {
        var_a1 = arg1;                                 u8 var_a1;
        for (...) { if (...) { var_a1 = i; } }   ->    for (...) { if (...) { var_a1 = i; } }
        ... return var_a1 + 1;                         ... return var_a1 + 1;

The copy of `$a1` and the local's width both change which registers the allocator hands out. On an N64 high-score style
insertion (SN GCC 2.8.1, `-O2 -mips3`, 81 instructions) the parameter list kept the match 315 off with every other step
done; dropping it with the local left a word was not enough either (415 on the finished source): the local had to be a
byte or halfword.

`stray_parameter_seed_drop` is offered when every parameter is either never named or named once, in a top-level
`local = param;` that is the local's first mention, and that local is also assigned elsewhere (so it is not a plain
copy of the parameter). The signature becomes `(void)`, the seeding statement goes, and the local is offered as `u8`,
`u16` and as it was.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stray_parameter_seed_drop'
FAMILIES = (FAMILY,)
WORD = r'(?:s32|u32|int|unsigned int|long)'


def _depth(text):
    return text.count('{') - text.count('}')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|va_list|__builtin_\w+)\b', part.body):
        return []
    clean = part.clean
    signature = re.search(r'\(([^()]*)\)\s*$', clean[:part.opening])
    if not signature or signature[1].strip() in ('', 'void'):
        return []
    parameters = []
    for text in signature[1].split(','):
        match = re.fullmatch(rf'[\w\s*]*?[\s*]({IDENT})\s*', text)
        if not match:
            return []
        parameters.append(match[1])
    base, end = part.opening + 1, part.end
    body = clean[base:end]
    seeds = []
    for param in parameters:
        uses = list(re.finditer(rf'(?<![\w.>]){param}\b', body))
        if not uses:
            continue
        if len(uses) != 1:
            return []
        seed = re.search(rf'(?<![\w.>])(?P<local>{IDENT})\s*=\s*{param}\s*;', body)
        if (not seed or _depth(body[:seed.start()]) != 0
                or not body[:seed.start()].rstrip().endswith((';', '{', '}', ''))):
            return []
        local = seed['local']
        declaration = re.search(rf'(?m)^(?P<lead>[ \t]*)(?P<type>{WORD})[ \t]+{local}[ \t]*;', body)
        if not declaration or declaration.end() > seed.start() or local in parameters:
            return []
        if re.search(rf'(?<![\w.>]){local}\b', body[declaration.end():seed.start()]) or re.search(rf'&\s*{local}\b', body):
            return []
        if not re.search(rf'(?<![\w.>]){local}\s*=(?!=)', body[seed.end():]):
            return []
        seeds.append((seed, declaration))
    if not seeds:
        return []
    out = []
    for kind in ('u8', 'u16', None):
        edits = [(signature.start(1), signature.end(1), 'void')]
        for seed, declaration in seeds:
            a, b = base + seed.start(), base + seed.end()
            line = clean.rfind('\n', 0, a) + 1
            stop = clean.find('\n', b)
            if stop >= 0 and not (clean[line:a] + clean[b:stop]).strip():
                a, b = line, stop + 1
            edits.append((a, b, ''))
            if kind:
                edits.append((base + declaration.start('type'), base + declaration.end('type'), kind))
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
