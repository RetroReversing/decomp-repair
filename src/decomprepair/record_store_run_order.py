"""A run of independent stores into local records, regrouped one record at a time in member order.

A 438-instruction N64 floor-height ray test (sn-n64-281 GCC 2.8.1, `-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float
-mfp32`) opens by filling two `Vec3f` probes and a `Vec3i` box from a parameter and constants:

    top.x = a->x; top.y = a->y + 100000.0f; top.z = a->z;
    bot.x = a->x; bot.y = a->y - 100000.0f; bot.z = a->z;
    below = 0.0f; above = 0.0f;
    box[0].x = -115; box[0].y = 2; box[0].z = -115; box[1].x = 115; box[1].y = 305; box[1].z = 115;

The first scheduler interleaves these stores, so the target's store order looks nothing like the source's, and a
move-one-line hill climb over the fourteen statements settled on a scrambled order that scored 257 (eleven prologue
rows still wrong). Written as above, one record at a time with its members in declaration order and the records in
the order the function declares them, the prologue matched (257 -> 210, measured with the app's judge-worker). The
scalar stores' places in the run did not matter there. Putting `bot` before `top` scored 336.

`variants` finds runs of two or more consecutive plain assignments (`name = e;`, `name.m = e;`, `name[k].m = e;` with a
literal `k`). The left-hand sides are all different, no right-hand side has a call, an assignment or an increment, and
no right-hand side reads anything the run writes, so the statements are independent and any order is the same
program. A run that stores into local records more than once and is not in record order already gets up to two
children: the record stores sorted by the record's declaration in the function, then its element, then the member's
place in its struct (read from `typedef struct { ... } Name;` in the source or the header), and the same with the
records in the order the run first stores into them. The scalar stores keep their places. The judge decides."""
import re

from .integer_repair_support import view

FAMILY = 'record_store_run_order'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'
STATEMENT = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>(?P<base>{IDENT})(?:\[(?P<index>\d+)\])?(?:\.(?P<member>{IDENT}))?)'
    rf'[ \t]*=(?!=)[ \t]*(?P<rhs>[^;\n]*);[ \t]*$')
TYPEDEF = re.compile(rf'typedef\s+struct\s*(?:{IDENT}\s*)?\{{(?P<body>[^{{}}]*)\}}\s*(?P<name>{IDENT})\s*;')
LOCAL = re.compile(rf'(?m)^[ \t]*(?P<type>{IDENT})[ \t]+(?P<names>[^;=(){{}}]*);')


def _struct_members(text):
    """{type name: {member: position}} for the plain `typedef struct { ... } Name;` definitions in the text."""
    found = {}
    for hit in TYPEDEF.finditer(text):
        members = []
        for field in hit['body'].split(';'):
            field = re.sub(r'\[[^\]]*\]', '', field).strip()
            if not field:
                continue
            words = re.split(r'\s+', field, maxsplit=1)
            if len(words) < 2:
                continue
            members += [part.strip().lstrip('*').strip() for part in words[1].split(',')]
        found[hit['name']] = {member: place for place, member in enumerate(members) if re.fullmatch(IDENT, member)}
    return found


def _locals(clean, lo, hi):
    """{name: (type, declaration position)} of the function's own top-level declarations."""
    found = {}
    for hit in LOCAL.finditer(clean, lo, hi):
        depth = clean.count('{', lo, hit.start()) - clean.count('}', lo, hit.start())
        if depth or hit['type'] in ('return', 'goto', 'else', 'case', 'do'):
            continue
        for part in hit['names'].split(','):
            name = re.match(rf'\s*\**\s*({IDENT})', part)
            if name and '*' not in part:
                found.setdefault(name[1], (hit['type'], hit.start()))
    return found


def _runs(clean, lo, hi):
    run, last_end = [], None
    for hit in STATEMENT.finditer(clean, lo, hi):
        between = clean[last_end:hit.start()] if last_end is not None else None
        if between is not None and between.strip() == '':
            run.append(hit)
        else:
            if len(run) >= 2:
                yield run
            run = [hit]
        last_end = hit.end()
    if len(run) >= 2:
        yield run


def _independent(run):
    lhs = [hit['lhs'].replace(' ', '') for hit in run]
    if len(set(lhs)) != len(lhs):
        return False
    written = {hit['base'] for hit in run}
    for hit in run:
        rhs = hit['rhs']
        if '(' in rhs and re.search(rf'{IDENT}\s*\(', rhs) or re.search(r'(?<![=!<>])=(?!=)|\+\+|--', rhs):
            return False
        if any(re.search(rf'(?<![\w.>]){re.escape(name)}\b', rhs) for name in written):
            return False
    return True


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    lo, hi = part.opening + 1, part.end - 1
    members = _struct_members((header or '') + '\n' + source)
    local = _locals(clean, lo, hi)
    out = []
    for run in _runs(clean, lo, hi):
        if not _independent(run):
            continue
        keys = {}
        for at, hit in enumerate(run):
            base, member = hit['base'], hit['member']
            if not member or base not in local or local[base][0] not in members:
                continue
            place = members[local[base][0]].get(member)
            if place is None:
                continue
            keys[at] = (base, int(hit['index'] or 0), place)
        if len(keys) < 3:
            continue
        first = {}
        for at in sorted(keys):
            first.setdefault(keys[at][0], at)
        slots = sorted(keys)
        for rank in ({base: local[base][1] for base in first}, first):
            order = sorted(slots, key=lambda at, rank=rank: (rank[keys[at][0]], keys[at][1], keys[at][2], at))
            if order == slots:
                continue
            placed = {slot: run[at] for slot, at in zip(slots, order)}
            pieces, cursor = [], run[0].start()
            for at, hit in enumerate(run):
                chosen = placed.get(at, hit)
                pieces.append(source[cursor:hit.start()])
                pieces.append(hit['indent'] + source[chosen.start('lhs'):chosen.end()])
                cursor = hit.end()
            child = source[:run[0].start()] + ''.join(pieces) + source[cursor:]
            out.append((FAMILY, child))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 900}  # the registry: no caller wiring (registry.py)
