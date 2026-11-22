"""A word stored through a raw offset next to a scalar global's read, as a structure member and a one-member record.

gcc 2.7.2's scheduler decides whether two memory references may conflict from their kinds (sched.c, `true_dependence`
and `output_dependence`): a reference through a structure member at a varying address ("in struct", `MEM_IN_STRUCT_P`)
never conflicts with a reference at a fixed address that is not in a structure; two plain references through a pointer
and a global always may. m2c writes every store as `*(s32 *)((char *)p + K)` and every global as a bare scalar, so
every store conflicts with every global: nothing moves across anything, and the second scheduler's priorities (the
length of the dependence chains ahead of each instruction) tie where the original's did not. The original's display
list words were members (`cmd->w1 = x`), its globals' reads were members too (`D_8010A4D8.x`, a record global), and the
mix is what orders the tail:

- the store `cmd->w1 = v` is in struct, so the store of a plain global right after it no longer waits for it (its
  chain is shorter), while the read of a *record* global still does (both are in struct), so it stays after the store;
- either change alone moved everything (670) or nothing (60); together they gave the original's order of the last two
  cursor advances in a 144-instruction N64 function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, 60 -> 0): the
  second scheduler picked `addiu $a2,$a2,8` ahead of the plain global's store because its chain was one longer, then
  stores after adds as the target has them. The scheduler trace (`-dS -dR`) showed the tie broken by the memory unit's
  potential hazard (a store before an add) until the store's chain was shorter. Read from sched.c (`priority`,
  `schedule_select`), not a guess.

`variants` offers, for a scalar global `G` (an `extern` word or half in the file, not `volatile`) read or written in the
function, and the raw offset stores `*(T *)((char *)p + K) = v;` through a local or parameter pointer on the lines just
before that use: the stores written as `((__repair_member_T_K *)p)->value = v;` one at a time and all together, and `G`
turned into a one-member record `__repair_global_T` with every use in the function (`G` is `G.value`). The judge decides.

When the stores are members already (`gp[0].words.w1 = v;`, `cmd->w0 = v;`: a source written with the SDK's macros or
a union `Gfx`) there is nothing to rewrite on the store side, and the global alone becomes the one-member record: the
read of a record global stays behind the member stores before it (both are in struct) where a plain global's read was
hoisted above them. A 343-instruction display-list function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) went
1195 -> 390 with the mode word's read as a member and 390 -> 255 with the border flag's; a second child reuses the record
type the first declared. The hoist is the scheduler's (`sched.c`, `true_dependence` of an in-struct and a plain
reference), the same rule as above.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .line_scan import lines

FAMILY = 'member_alias_pair'
FAMILIES = (FAMILY,)
LIMIT = 8
NEAR = 12  # lines between a raw store and the global's use
SIZES = {'s32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 's16': 2, 'u16': 2, 'short': 2, 'unsigned short': 2}
TYPE = '|'.join(sorted((re.escape(t).replace(r'\ ', r'\s+') for t in SIZES), key=len, reverse=True))
STORE = re.compile(
    rf'(?P<lhs>\*\s*\(\s*\(\s*(?P<type>{TYPE})\s*\*\s*\)\s*\(+\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<var>{IDENT})\s*\)?'
    rf'\s*\+\s*(?P<off>{NUMBER})\s*\)+\s*\))\s*=(?!=)')
STORE_PLAIN = re.compile(
    rf'(?P<lhs>\*\s*\(\s*(?P<type>{TYPE})\s*\*\s*\)\s*\(+\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<var>{IDENT})\s*'
    rf'\+\s*(?P<off>{NUMBER})\s*\)+)\s*=(?!=)')
# A store that already goes through a structure or union member (`gp[0].words.w1 = v;`, `cmd->w0 = v;`): the source
# was written with the display-list words as members, so only the global's read still needs to become one.
MEMBER_STORE = re.compile(
    rf'^[ \t]*\(?{IDENT}(?:\s*\[[^\]\n]*\])?(?:\s*(?:->|\.)\s*{IDENT}(?:\s*\[[^\]\n]*\])?)+\s*\)?\s*=(?!=)')
EXTERN = re.compile(rf'(?m)^(?P<indent>[ \t]*)extern\s+(?P<type>{TYPE})\s+(?P<name>{IDENT})\s*;[ \t]*$')


def _norm(type_):
    return re.sub(r'\s+', ' ', type_)


def _typedef_name(prefix, type_, extra=''):
    return f'__repair_{prefix}_{_norm(type_).replace(" ", "_")}{extra}'


def _definition_start(clean, opening):
    return max(clean.rfind(ch, 0, opening) for ch in ';}') + 1


def _uses(text, name):
    return re.compile(rf'(?<![\w.>])({re.escape(name)})(?![\w])').finditer(text)


def _build(source, start, body, glob, kinds, chosen):
    """`source` with the chosen raw stores as members and the global as a one-member record, or None."""
    gname, decl, gtype, record = glob
    edits = []
    for index, hit in chosen:
        line = body[index]
        member = kinds[(_norm(hit['type']), int(hit['off'], 0))]
        edits.append((line.start + hit.start('lhs'), line.start + hit.end('lhs'), f'((({member} *) {hit["var"]})->value)'))
    for line in body:
        edits += [(line.start + use.start(), line.start + use.end(), f'{gname}.value') for use in _uses(line.text, gname)]
    spans = sorted((s, e) for s, e, _ in edits)
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        return None
    typedefs = ''.join(f'typedef struct {{ {f"char pad[{off}]; " if off else ""}{t} value; }} {kinds[(t, off)]};\n'
                       for t, off in sorted({(_norm(h['type']), int(h['off'], 0)) for _, h in chosen}))
    if f'}} {record};' not in source[:start]:  # an earlier child of this family already declared the record
        typedefs += f'typedef struct {{ {gtype} value; }} {record};\n'
    head = source[:start]
    head = head[:decl.start()] + typedefs + f'{decl["indent"]}extern {record} {gname};' + head[decl.end():]
    return head + edit(source[start:], [(s - start, e - start, r) for s, e, r in edits])


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body) or '__repair_member_' in part.clean:
        return []
    before = part.clean[:part.opening]
    start = _definition_start(part.clean, part.opening)
    body = lines(part, source)
    outside = part.clean[:start] + part.clean[part.end:]
    declared = {m['name']: m for m in EXTERN.finditer(part.clean[:start])
                if len(re.findall(rf'(?<![\w.]){re.escape(m["name"])}\b', outside)) == 1
                and not re.search(rf'\b{re.escape(m["name"])}\b', part.clean[start:part.opening])}
    if not declared:
        return []
    volatile = set(re.findall(rf'\bvolatile\b[^;]*?\b({IDENT})\s*;', before))
    stores = []
    for index, line in enumerate(body):
        if re.search(r'[{}]', line.text) or line.text.count('=') < 1:
            continue
        hit = STORE.search(line.text) or STORE_PLAIN.search(line.text)
        if not hit or hit.start() != len(line.indent) or int(hit['off'], 0) % SIZES[_norm(hit['type'])]:
            continue
        stores.append((index, hit))
    member_stores = [index for index, line in enumerate(body)
                     if not re.search(r'[{}]', line.text) and MEMBER_STORE.match(line.text)]
    if not stores and not member_stores:
        return []
    results = []
    for gname, decl in declared.items():
        if gname in volatile:
            continue
        users = [i for i, line in enumerate(body) if any(_uses(line.text, gname))]
        if not users:
            continue
        near = [(i, hit) for i, hit in stores
                if any(0 < u - i <= NEAR and not any(re.search(r'[{}]|\bgoto\b|\breturn\b', body[k].text) for k in range(i, u))
                       for u in users)]
        if not near:
            # the words are members already: the global alone becomes the one-member record (a store through a
            # member does not conflict with a read of a plain global in the scheduler, a read of a member does)
            if any(0 < u - i <= NEAR and not any(re.search(r'[{}]|\bgoto\b|\breturn\b', body[k].text)
                                                for k in range(i, u))
                   for i in member_stores for u in users):
                text = _build(source, start, body, (gname, decl, _norm(decl['type']), _typedef_name('global', _norm(decl['type']))), {}, [])
                if text and (FAMILY, text) not in results:
                    results.append((FAMILY, text))
                if len(results) >= LIMIT:
                    return results
            continue
        gtype = _norm(decl['type'])
        record = _typedef_name('global', gtype)
        kinds = {}
        for _, hit in near:
            kinds[(_norm(hit['type']), int(hit['off'], 0))] = _typedef_name('member', hit['type'], f'_{int(hit["off"], 0):X}')

        children = []
        if len(near) > 1:
            children.append(near)
        children.extend([[pair] for pair in sorted(near, key=lambda p: -p[0])])
        for chosen in children:
            text = _build(source, start, body, (gname, decl, gtype, record), kinds, chosen)
            if text and (FAMILY, text) not in results:
                results.append((FAMILY, text))
            if len(results) >= LIMIT:
                return results
    return results
