"""Stores through one pointer, computed into locals first and stored together at the end.

A routine that transforms a vector in place, or into an output that may be its input, is written
`x = ...; y = ...; z = ...; out[0] = x; out[1] = y; out[2] = z;` so the inputs are all read before any is
overwritten. gcc 2.7.2 can't move a load through a pointer past a store through another that may alias it, so the
game's code computes all three sums and stores them last. m2c writes each store with its sum, and the loads of the
vector it hoisted into temporaries:

    temp_ft2 = M2C_FIELD(arg1, f32 *, 0);  ...
    M2C_FIELD(arg2, f32 *, 0) = (f32) ((M2C_FIELD(arg0, f32 *, 0) * temp_ft2) + ...);
    M2C_FIELD(arg2, f32 *, 4) = ...;

Four N64 matrix-times-vector functions were 54.8% so; with the sums in locals and the vector's loads where they are
used, exact (with the temporaries kept, 99%). Both are offered. The meaning is unchanged: every load still happens
before the first store.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'deferred_stores'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)M2C_FIELD\(\s*(?P<base>' + IDENT + r')\s*,\s*(?P<type>' + IDENT
                   + r')\s*\*\s*,\s*(?P<off>0x[0-9A-Fa-f]+|\d+)\s*\)\s*=(?!=)\s*(?P<value>[^;{}]+);[ \t]*\n')
LOAD_TEMP = re.compile(r'(?m)^[ \t]*(?P<name>' + IDENT + r')\s*=\s*(?P<load>M2C_FIELD\([^;{}]*\))\s*;[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    runs, run = [], []
    for hit in STORE.finditer(clean, opening, end):
        if run and (hit.start() != run[-1].end() or hit['base'] != run[0]['base']
                    or hit['indent'] != run[0]['indent']):
            if len(run) >= 2:
                runs.append(run)
            run = []
        run.append(hit)
    if len(run) >= 2:
        runs.append(run)
    result = []
    for run in runs:
        values = [source[h.start('value'):h.end('value')].strip() for h in run]
        if not all('M2C_FIELD' in v for v in values) or any(re.search(r'\b(?!M2C_FIELD\b)' + IDENT + r'\s*\(', v)
                                                             for v in values):
            continue
        indent = run[0]['indent']
        names = [f'__repair_store_{i}' for i in range(len(run))]
        block = ''.join(f'{indent}{n} = {v};\n' for n, v in zip(names, values))
        block += ''.join(f'{indent}M2C_FIELD({h["base"]}, {h["type"]} *, {h["off"]}) = {n};\n'
                         for h, n in zip(run, names))
        decls = ''.join(f'\n    {h["type"]} {n};' for h, n in zip(run, names))
        text = source[:run[0].start()] + block + source[run[-1].end():]
        text = text[:opening + 1] + decls + text[opening + 1:]
        result.append((FAMILY, text))
        inlined = _inline_loads(text, name, names)
        if inlined and inlined != text:
            result.append((FAMILY, inlined))
    return result[:4]


def _inline_loads(source, name, names):
    """Temporaries m2c assigned once from a load, before the sums and used only in them, written at their uses."""
    text, done = source, set()
    while True:
        step = _inline_one(text, name, names, done)
        if step is None:
            return text
        text, var = step
        done.add(var)


def _inline_one(source, name, names, done):
    span = find(source, name)
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}')
    first_sum = clean.find(names[0] + ' =', opening, end)
    first_store = clean.find('= ' + names[0] + ';', opening, end)
    if first_sum < 0 or first_store < 0:
        return None
    for temp in LOAD_TEMP.finditer(clean, opening, first_sum):
        var = temp['name']
        if var in done or var in names:
            continue
        mentions = [m.start() for m in re.finditer(r'(?<![\w.>])' + var + r'\b', clean[opening:end])]
        uses = [opening + p for p in mentions if first_sum <= opening + p < first_store]
        assigned = re.findall(r'(?<![\w.>])' + var + r'\s*=(?!=)', clean[opening:end])
        declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', clean[opening:temp.start()])
        if len(assigned) != 1 or not declared or not uses or len(mentions) != len(uses) + 2:
            continue
        load = source[temp.start('load'):temp.end('load')]
        text = source
        for at in reversed(uses):
            text = text[:at] + load + text[at + len(var):]
        text = text[:temp.start()] + text[temp.end():]
        decl_at = opening + declared.start()
        text = text[:decl_at] + text[opening + declared.end():]
        return text, var
    return None
