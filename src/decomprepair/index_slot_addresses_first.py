"""A run of lookups through one index table, with every slot's address taken before the first load.

    a = &verts[table[i0]];              p0 = &table[i0];
    b = &verts[table[i1]];      ->      p1 = &table[i1];
    c = &verts[table[i2]];              p2 = &table[i2];
                                        a = &verts[*p0];
                                        b = &verts[*p1];
                                        c = &verts[*p2];

Written in one statement each, GCC loads each entry right after building its address. A target that builds all the
addresses first (`addu`, `addu`, `addu`, then the three `lw` through the same registers) had the slots named: a
209-instruction N64 triangle emitter (SN GCC 2.8.1 `-G0 -mips3 -O2`) went 1920 -> 1320 with it (measured with the app's
judge; one function). Nothing is stored between the statements, so each entry reads the same value.

`variants` looks for two to four assignments that follow one another, each `x = ...TABLE[I]...;` with the one `TABLE`
a pointer the function declares `T *TABLE`, `x` a local that is neither `TABLE` nor any index of the run, and no call,
`++` or `--`. The judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'index_slot_addresses_first'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'
LINE = re.compile(rf'[ \t]*(?P<target>{IDENT})[ \t]*=(?!=)(?P<value>[^;{{}}\n]*);[ \t]*')
LOOKUP = re.compile(rf'(?<![\w.>&])(?P<table>{IDENT})[ \t]*\[[ \t]*(?P<index>{IDENT})[ \t]*\](?![ \t]*(?:\[|\.|->))')


def _lookup(line):
    """(match, [lookups of the statement's value by table]) of a plain `x = ...;` line, or None."""
    stmt = LINE.fullmatch(line)
    if not stmt or re.search(rf'\+\+|--|\b(?!sizeof\b){IDENT}\s*\((?!\s*(?:{IDENT}\s*)?\*+\s*\))', stmt['value']):
        return None
    return stmt, list(LOOKUP.finditer(line, stmt.start('value'), stmt.end('value')))


def _children(source, name):
    """One child per run, each on its own."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end] or re.search(r'\b(?:asm|__asm__|volatile)\b', clean[opening:end]):
        return []
    function = clean[span[0]:end]
    taken = [int(n) for n in re.findall(r'\bslot(\d+)\b', function)]
    base = max(taken, default=-1) + 1
    lines = clean[opening:end].splitlines(keepends=True)
    starts, at = [], opening
    for line in lines:
        starts.append(at)
        at += len(line)
    out, i = [], 1
    while i < len(lines) and len(out) < LIMIT:
        first = _lookup(lines[i].rstrip('\n'))
        tables = {m['table'] for m in first[1]} if first else set()
        used = None
        for table in sorted(tables):
            kind = re.search(rf'\b((?:(?:const|struct|union|unsigned|signed)\s+)*{IDENT})\s*\*\s*{table}\s*(?=[,;)=])',
                             function)
            if not kind:
                continue
            run, j = [], i
            while j < len(lines) and len(run) < 4:
                found = _lookup(lines[j].rstrip('\n'))
                hits = [m for m in found[1] if m['table'] == table] if found else []
                if len(hits) != 1:
                    break
                run.append((j, found[0]['target'], hits[0]))
                j += 1
            targets = {target for _, target, _ in run}
            read = {table} | {hit['index'] for _, _, hit in run}
            if len(run) < 2 or targets & read or len(targets) != len(run) \
                    or any(re.search(rf'&\s*{target}\b', function) for target in targets) \
                    or any(not re.search(rf'\b{IDENT}[ \t*]+{target}\s*(?=[;,)=\[])|,\s*\*?\s*{target}\s*(?=[,;])', function)
                           for target in targets):
                continue
            used = (table, kind[1], run, j)
            break
        if not used:
            i += 1
            continue
        table, kind, run, j = used
        indent = re.match(r'[ \t]*', lines[i])[0]
        takes = [f'{indent}slot{base + n} = &{table}[{hit["index"]}];\n' for n, (_, _, hit) in enumerate(run)]
        reads = []
        for n, (row, _, hit) in enumerate(run):
            begin = starts[row]
            reads.append(source[begin:begin + hit.start()] + f'*slot{base + n}' + source[begin + hit.end():begin + len(lines[row])])
        text = source[:starts[i]] + ''.join(takes + reads) + source[starts[j - 1] + len(lines[j - 1]):]
        head = text.index('\n', opening) + 1
        declared = ', '.join(f'*slot{base + n}' for n in range(len(run)))
        text = text[:head] + f'    {" ".join(kind.split())} {declared};\n' + text[head:]
        out.append((FAMILY, text))
        i = j
    return out


def variants(source, name):
    out = _children(source, name)
    if len(out) > 1:  # copies of one run in two loops only pay off together
        every = source
        for _ in range(LIMIT):
            child = _children(every, name)
            if not child:
                break
            every = child[0][1]
        out.insert(0, (FAMILY, every))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 906}  # registry.py
