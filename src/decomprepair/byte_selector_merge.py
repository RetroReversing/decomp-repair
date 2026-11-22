"""One byte held in several integer locals (`raw = *p; ... opcode = raw & 255;`), merged into a single `u8` local.

m2c keeps a byte it reads in a word local and the masked copy it switches on in another (`raw = *p; opcode = raw & 255;
switch (opcode)`), and an earlier repair may add a third for the reload at a loop's tail. The game declared one
`unsigned char`: the loop test, the switch and the reload all read it. With three locals the allocator ranks three
short ranges and the entry compare reads the unmasked load; with one `u8` the load, the `andi` the switch needs and
the compare fall where the target has them. On a KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 87-instruction
N64 record-stream walker this was 285 -> 70 together with the collapse of the identical-arm guard that read one of the
locals before it was ever set (the guard alone made the saved 130 worse, 285; the merge cannot happen while the dead
read keeps a second local alive), so a child carries both edits, and the merge is also offered alone.

Only locals whose every write is a load through a `u8 *` (`*p`, `p[i]`) or a `& 255` of another member (the members of
one chain), whose address is never taken, and where no load of the chain lies between a member's last write and a read
of it, so each read sees the byte the single local holds. The member that is masked survives, retyped `u8`; the
others' declarations go, their mentions are renamed and the now-empty `x = x & 255;` is dropped. A hypothesis for the
exact judge, not an equivalence claim."""
import re

from . import identical_arm_collapse_repairs
from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_selector_merge'
FAMILIES = (FAMILY,)
COLLAPSES = 3
_TYPE = r'(?:(?:unsigned|signed)\s+)?(?:int|long|short|char)|[su](?:8|16|32)|(?:unsigned|signed)'
_DECL = re.compile(rf'(?:^|(?<=[;{{}}]))(?P<lead>\s*)(?P<type>{_TYPE})\s+(?P<name>{IDENT})\s*;')
_MASK = re.compile(rf'(?<![\w.>])(?P<x>{IDENT})\s*=\s*(?P<y>{IDENT})\s*&\s*(?:255|0[xX][fF]{{2}})[uU]?\s*;')
_WRITE = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*(?P<w>{IDENT})')


def _pointers(clean, name):
    start = max(clean.rfind(name+'(') , 0)
    return set(re.findall(rf'(?:\bu8|unsigned\s+char)\s*\*\s*({IDENT})', clean[start:]))


def _merge(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    declared = {d['name']: d for d in _DECL.finditer(clean, part.opening+1, part.end-1)}
    declared = {n: d for n, d in declared.items() if not re.search(rf'&\s*{n}\b', part.body)}
    pointers = _pointers(clean, name)
    load = re.compile(rf'(?<![\w.>])(?P<z>{IDENT})\s*=\s*(?:\*\s*(?P<p>{IDENT})|(?P<q>{IDENT})\s*\[[^\[\]]*\])\s*;')
    loads = {h.start('z'): h for h in load.finditer(clean, part.opening+1, part.end-1)
             if h['z'] in declared and (h['p'] or h['q']) in pointers}
    masks = {h.start('x'): h for h in _MASK.finditer(clean, part.opening+1, part.end-1)
             if h['x'] in declared and h['y'] in declared and h['x'] != h['y']}
    if not masks:
        return []
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            a = parent[a]
        return a
    for h in masks.values():
        parent[find(h['x'])] = find(h['y'])
    chains = {}
    for member in list(parent):
        chains.setdefault(find(member), set()).add(member)
    out = []
    for members in chains.values():
        writes = [(h.start(), h['v'] or h['w']) for h in _WRITE.finditer(clean, part.opening+1, part.end-1)
                  if (h['v'] or h['w']) in members]
        owned = {h.start('x') for h in masks.values() if h['x'] in members} | {h.start('z') for h in loads.values()
                                                                               if h['z'] in members}
        if len(members) < 2 or any(at not in owned for at, _ in writes):
            continue
        survivor = sorted(h['x'] for h in masks.values() if h['x'] in members)[0]
        # No load of the chain between a member's last write and a read of it.
        reads = [(part.opening+1+r.start(), r[0]) for m in members
                 for r in re.finditer(rf'(?<![\w.>])\b{m}\b', clean[part.opening+1:part.end-1])]
        written = {at for at, _ in writes}
        load_at = sorted(h.start('z') for h in loads.values() if h['z'] in members)
        last, ok = {}, True
        for at, kind, v in sorted([(at, 'w', v) for at, v in writes] + [(at, 'r', v) for at, v in reads if at not in written]):
            if kind == 'w':
                last[v] = at
            elif v in last and any(last[v] < point < at for point in load_at):
                ok = False
        if not ok:
            continue
        # Rename every mention of the others to the survivor, drop their declarations and the empty masks.
        spans = []
        for m in members:
            d = declared[m]
            if m == survivor:
                spans.append((d.start('type'), d.end('type'), 'u8'))
            else:
                spans.append((d.start(), d.end(), ''))
        for m in members - {survivor}:
            for ref in re.finditer(rf'(?<![\w.>])\b{m}\b', clean[part.opening+1:part.end-1]):
                at = part.opening+1+ref.start()
                if not any(s <= at < e for s, e, _ in spans):
                    spans.append((at, at+len(m), survivor))
        text = edit(source, spans)
        text = re.sub(rf'[ \t]*(?<![\w.>]){survivor}\s*=\s*{survivor}\s*&\s*(?:255|0[xX][fF]{{2}})[uU]?\s*;[ \t]*\n?', '', text)
        if text != source:
            out.append((FAMILY, text))
    return out


def variants(source, name, header=''):
    out = []
    for text in [source]+[t for _, t in identical_arm_collapse_repairs.variants(source, name, header)[:COLLAPSES]]:
        out.extend(_merge(text, name))
    out = [(f, t) for f, t in out if t != source]
    return list(dict.fromkeys(out))[::-1]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 65}  # the registry: no caller wiring (registry.py)
