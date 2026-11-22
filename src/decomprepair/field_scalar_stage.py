"""Vector fields kept in scalar locals: a local record's written fields staged, a pointer's repeated field reads cached.

m2c and a plain transcription read `p->y` at every use and `v.x` back from the record it just stored. The game's code
(a 178-instruction ray and triangle test, N64, KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`) kept the values in
locals: each component of a difference was assigned to a scalar and stored to the record from it, and the direction
vector's three components were each read once into a scalar. From the plain form the score went 7935 -> 860 with the
cached direction reads, 650 with the first of them read through a `const volatile` pointer, and 0 with the differences
staged as well, after two statement-order steps `allocation_lever` already offers (650 -> 230 -> 0); none was better
as the others' prerequisite. Scalars are what the allocator can put in a register class of their own (float pseudos
with `GR_REGS` as the alternate class, global.c), and the order they are declared in is the tie-break between equal
priorities, so each variant also says where the new declarations go. The explanation is read from `-dl -dg` dumps, a
hypothesis, not from the compiler's source.

Variants (each needs at least one of the two edits; the combination is one child, since neither alone reached 0):

* stage: for every local record variable whose fields are each assigned by exactly one statement and read later,
  `v.f = expr;` becomes `v_f = expr;` followed by `v.f = v_f;`, and the later reads of `v.f` read `v_f`;
* cache: for a pointer parameter whose float fields are read at least twice, one read of each into `p_f` in a block
  before the first statement that reads any of them (in field order or reversed), with the first read through a
  `const volatile` pointer or not; only when no statement before the last use stores through a pointer or calls.

Only straight-line bodies are rewritten (no braces inside the function), and a record whose address is taken is left
alone. The declarations go after the existing ones, the staged group before the cached one or after it.
"""
import re
from itertools import combinations

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'field_scalar_stage'
FAMILIES = (FAMILY,)

STRUCT = re.compile(r'typedef\s+struct\s*\w*\s*\{([^{}]*)\}\s*(\w+)\s*;')
FIELD = re.compile(r'\b(f32|float)\s+([\w\s,]+);')
MAX_PAIRS = 4
EARLY = (0, 1, 2, 3)
DECL = re.compile(r'^[ \t]*(?:const[ \t]+)?[A-Za-z_]\w*(?:[ \t]+\w+)*[ \t]+\**[ \t]*\w+(?:\[\d+\])?(?:[ \t]*,[ \t]*\**[ \t]*\w+(?:\[\d+\])?)*[ \t]*;[ \t]*$')


def _structs(source):
    """{record type: [float field names in order]} of the plain records made only of floats."""
    found = {}
    for record in STRUCT.finditer(_blank(source)):
        fields = []
        for kind, names in FIELD.findall(record[1]):
            fields += [n.strip() for n in names.split(',')]
        if fields and not re.sub(r'\b(?:f32|float)\b|[\w\s,;]', '', record[1]) and len(re.findall(r'\bf32\b|\bfloat\b', record[1])) == len(FIELD.findall(record[1])):
            found[record[2]] = fields
    return found


def _split(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    paren, opening = clean.find('(', span[0], span[1]), clean.find('{', span[0], span[1])
    if paren < 0 or opening < 0 or (end := close(clean, opening, '{', '}')) is None:
        return None
    shut = close(clean, paren, '(', ')')
    if shut is None or shut > opening:
        return None
    inner = source[opening + 1:end - 1]
    if '{' in clean[opening + 1:end - 1] or '}' in clean[opening + 1:end - 1]:
        return None
    lines = inner.split('\n')
    cut = 0
    while cut < len(lines) and (not lines[cut].strip() or (DECL.match(lines[cut]) and '=' not in lines[cut])):
        cut += 1
    return source[paren + 1:shut - 1], opening, end, lines[:cut], lines[cut:]


def _stage(types, structs, declared, statements, chosen=None):
    """(new statements, scalar names per record) with every fully assigned local record's fields staged, or None."""
    out, staged = list(statements), {}
    for record, fields in declared.items():
        if chosen is not None and record not in chosen:
            continue
        kind = types[record]
        writes = {f: [i for i, s in enumerate(statements) if re.match(rf'\s*{record}\.{f}\s*=(?!=)', s)] for f in structs[kind]}
        if any(len(w) != 1 for w in writes.values()) or re.search(rf'&\s*{record}\b', '\n'.join(statements)):
            continue
        staged[record] = {f: f'{record}_{f}' for f in structs[kind]}
    if not staged:
        return None
    result = []
    for line in out:
        for record, names in staged.items():
            for f, scalar in names.items():
                write = re.match(rf'(\s*){record}\.{f}\s*=(?!=)\s*(.*);\s*$', line)
                if write:
                    line = f'{write[1]}{scalar} = {write[2]};\n{write[1]}{record}.{f} = {scalar};'
                else:
                    line = re.sub(rf'(?<![\w.>]){record}\.{f}\b(?!\s*=(?!=))', scalar, line)
        result.append(line)
    return result, staged


def _cache(structs, pointers, statements, order, volatile, chosen=None, early=0):
    """(new statements, {pointer: {field: scalar}}) with each pointer's repeated float reads cached, or None.

    The loads go in one block before the first statement that reads a cached field; `volatile` reads the last field
    of each pointer's record through a `const volatile` pointer, and `early` puts that load that many statements
    above the block (loads of read-only memory cross statements that write other things)."""
    cached, first = {}, None
    for pointer, kind in pointers.items():
        if chosen is not None and pointer not in chosen:
            continue
        reads = {f: sum(len(re.findall(rf'(?<![\w.>]){pointer}->{f}\b(?!\s*=(?!=))', s)) for s in statements) for f in structs[kind]}
        writes = sum(len(re.findall(rf'(?<![\w.>]){pointer}->\w+\s*=(?!=)', s)) for s in statements)
        fields = [f for f in structs[kind] if reads[f] >= 2]
        if fields and not writes:
            cached[pointer] = (kind, fields)
    if not cached:
        return None
    for pointer, (kind, fields) in cached.items():
        uses = [i for i, s in enumerate(statements) if any(re.search(rf'(?<![\w.>]){pointer}->{f}\b', s) for f in fields)]
        for i in range(uses[-1]):
            if re.search(r'(?<![\w.>])\*\s*\w+\s*=(?!=)|\w+\s*->\s*\w+\s*=(?!=)|\w+\s*\[[^\]]*\]\s*=(?!=)|\b\w+\s*\(', statements[i]) and not re.match(r'\s*if\s*\(', statements[i]):
                return None
        first = uses[0] if first is None else min(first, uses[0])
    names, loads, hoisted = {}, [], []
    for pointer, (kind, fields) in cached.items():
        names[pointer] = {f: f'{pointer}_{f}' for f in fields}
        for f in (reversed(fields) if order else fields):
            if volatile and f == fields[-1]:
                load = f'    {pointer}_{f} = ((const volatile {kind} *){pointer})->{f};'
                (hoisted if early else loads).append(load)
            else:
                loads.append(f'    {pointer}_{f} = {pointer}->{f};')
    if early and (not hoisted or first - early < 0):
        return None
    result = []
    for i, line in enumerate(statements):
        if i == first - early and hoisted:
            result += hoisted
        if i == first:
            result += loads
        for pointer, fields in names.items():
            for f, scalar in fields.items():
                line = re.sub(rf'(?<![\w.>]){pointer}->{f}\b', scalar, line)
        result.append(line)
    return result, names


def variants(source, name):
    structs = _structs(source)
    split = _split(source, name) if structs else None
    if not split:
        return []
    params, opening, end, decls, statements = split
    pointers, types = {}, {}
    for piece in params.split(','):
        hit = re.match(r'\s*(?:const\s+)?(\w+)\s*\*\s*(\w+)\s*$', piece)
        if hit and hit[1] in structs:
            pointers[hit[2]] = hit[1]
    declared = {}
    for line in decls:
        hit = re.match(r'\s*(\w+)\s+(\w+(?:\s*,\s*\w+)*)\s*;', line)
        if hit and hit[1] in structs:
            for v in hit[2].split(','):
                declared[v.strip()] = []
                types[v.strip()] = hit[1]
    staged = _stage(types, structs, declared, statements) if declared else None
    records = list(staged[1]) if staged else []
    subsets = [tuple(records)] if records else []
    subsets += [(r,) for r in records if len(records) > 1] + [pair for pair in combinations(records, 2) if len(records) > 2][:MAX_PAIRS]
    found = []
    cacheable = [p for p in pointers if _cache(structs, {p: pointers[p]}, statements, False, False)]
    subsets_of_pointers = [(p,) for p in cacheable] + ([tuple(cacheable)] if len(cacheable) > 1 else [])
    caches = [None] + [(subset, False, False, 0) for subset in subsets_of_pointers]
    caches += [(subset, True, r, k) for subset in subsets_of_pointers for r in (False, True) for k in ((0,) if not r else EARLY)]
    for chosen in [None] + subsets:
        for cache in caches:
            for cache_first in ((False, True) if chosen and cache else (False,)):
                if chosen is None and cache is None:
                    continue
                body, groups = list(statements), []
                if chosen:
                    body, stage_names = _stage(types, structs, declared, body, chosen)
                    groups.append([n for names in stage_names.values() for n in names.values()])
                if cache:
                    made = _cache(structs, pointers, body, cache[2], cache[1], cache[0], cache[3])
                    if not made:
                        continue
                    body, cache_names = made
                    groups.append([n for names in cache_names.values() for n in names.values()])
                if cache_first:
                    groups.reverse()
                new = [f'    f32 {", ".join(names)};' for names in groups]
                candidate = source[:opening + 1] + '\n'.join(decls + new + body) + source[end - 1:]
                if candidate != source and (FAMILY, candidate) not in found:
                    found.append((FAMILY, candidate))
    return found
