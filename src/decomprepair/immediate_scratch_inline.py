"""A scratch local that only carries a value to the next statement, written at that statement.

A draft (or a search that wanted every intermediate in a register of its own) keeps one scratch for the half of an
expression the author wrote inline: `y = (x - k) + (r + r) - s; b = y * h2;`, then the same `y` again for `c`. Each
`y = E;` is read once, by the statement right after it, and the next `y = ...;` starts a new value. The original has
`b = (E) * h2;`: the scratch is a multi-set pseudo (global.c, not local-alloc.c) with a live range of two insns that the
scheduler cannot move across, and in a block that repeats for other axes it is what keeps the first block from having
the shape of the others (a repeated-block rewrite sees `y = ...; b = y * h2;` in one block and `b = (...) * h2;` in the
rest). Found while matching a 163-instruction float function (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): the first
of its three blocks was written through that scratch and the other two were not.

`variants` offers, for each scalar local that is assigned at least twice, the function with every assignment inlined that
is read exactly once, by the statement right after it, with the value's operands unchanged by that statement
(`immediate_scratch_inline`). The assignments that are read elsewhere stay, so a scratch that is also a copy of a
parameter keeps those. A candidate rewrite; the exact judge decides.
"""
import re

from .repeated_block_scratch_reuse import _declared, _function, _mentions, _statements

FAMILY = 'immediate_scratch_inline'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NAMED = r'(?<![\w.>])' + IDENT
BLOCKERS = re.compile(r'\b(?:for|while|do|goto|switch|if|else)\b')


def variants(source, name):
    body = _function(source, name)
    if not body:
        return []
    clean, opening, end, start = body
    declared = _declared(clean, opening, end)
    if not declared or BLOCKERS.search(clean[opening:end]):
        return []
    statements = _statements(clean, declared[-1][2][1], end - 1)
    text = [clean[a:b] for a, b in statements]
    edits = []
    for _, names, _ in declared:
        for local in names:
            sets = [i for i, t in enumerate(text) if re.match(rf'\s*{re.escape(local)}\s*=(?!=)', t)]
            if len(sets) < 2:
                continue
            inlined = []
            for i in sets:
                value = re.match(rf'\s*{re.escape(local)}\s*=\s*(?P<value>[^;]*);', text[i])['value'].strip()
                if i + 1 >= len(text) or re.search(rf'{IDENT}\s*\(|=|\+\+|--', value) or local in re.findall(NAMED, value):
                    continue
                later = [j for j in range(i + 1, len(text)) if _mentions(text[j], local, 0, len(text[j]))]
                nxt = text[i + 1]
                lhs = re.match(rf'\s*(?P<lhs>{IDENT})\s*=(?!=)', nxt)
                if later[:1] != [i + 1] or len(_mentions(nxt, local, 0, len(nxt))) != 1:
                    continue
                if later[1:] and later[1] not in sets:
                    continue
                if lhs and lhs['lhs'] in set(re.findall(NAMED, value)):
                    continue
                inlined.append((i, value))
            for i, value in inlined:
                a, b = statements[i]
                edits.append((a, b, ''))
                ra, rb = statements[i + 1]
                wrapped = value if re.fullmatch(r'[\w.]+', value) else f'({value})'
                edits += [(at, at + len(local), wrapped) for at in _mentions(clean, local, ra, rb)]
    if not edits:
        return []
    out = source
    for a, b, replacement in sorted(edits, reverse=True):
        out = out[:a] + replacement + out[b:]
    return [(FAMILY, out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
