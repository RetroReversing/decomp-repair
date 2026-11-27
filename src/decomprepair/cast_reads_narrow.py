"""A word local that is only ever read through one narrow cast, declared that narrow.

m2c has no type for a value that lives in a saved register across calls, so a `s16` angle comes back as a word local
with the cast written at every read: `u32 angle; angle = next() >> 3; ... sine((s16) angle) ... cosine((s16) angle)`.
The program is the same as `s16 angle` read bare, and the words are not: the narrow local is another machine mode, so
the first scheduler and the allocator treat its set differently. On a 111-instruction N64 object initialiser (SN64 GCC,
`-O2 -mips3`) this was the last step: 80 -> 0, the shift after a call went back ahead of the stores that follow it.
That the machine mode is what moves it is a hypothesis; the judge decides each child.

`masked_reads_narrow` does not offer it: it takes only unsigned masks and counters written with literals.

`cast_reads_narrow` offers, for each word local (`s32`, `u32`, `int`, `unsigned`; declared once, no initialiser, its
address never taken) whose reads are all `(T) v` for one narrow `T` and whose writes are whole statements (`=`, `+=`,
`-=`, `&=`, `|=`, `^=`, `++`, `--`: each keeps its low bits whether the local is a word or narrow), the local declared
`T` with the casts dropped, one child with all of them first when there are several. `variants` returns
[(family, source)]."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'cast_reads_narrow'
FAMILIES = (FAMILY,)
LIMIT = 6
_DECL = re.compile(r'(?<=[;{}])(?P<space>\s*)(?P<type>s32|u32|int|signed\s+int|unsigned\s+int|unsigned)\s+'
                   r'(?P<name>[A-Za-z_]\w*)\s*;')
_CAST = r'\(\s*(?P<cast>s16|u16|s8|u8)\s*\)\s*'


def _uses(clean, var, start, end, decl):
    """(kind, [(start, end) of each cast read]) when every use of `var` allows the narrow type, else None."""
    kinds, reads, writes, taken = set(), [], 0, []
    for hit in re.finditer(rf'{_CAST}{var}\b(?!\s*(?:\[|\.|->|\+\+|--|\(|(?:<<|>>|[-+*/%&|^])?=(?!=)))', clean[:end]):
        if hit.start() >= start:
            kinds.add(hit['cast'])
            reads.append((hit.start(), hit.end()))
            taken.append((hit.start(), hit.end()))
    if len(kinds) != 1:
        return None
    for hit in re.finditer(rf'(?<![\w.>]){var}\b', clean[:end]):
        at = hit.start()
        if at < start or decl.start() <= at < decl.end() or any(a <= at < b for a, b in taken):
            continue
        before = clean[start - 1:at].rstrip()
        if before.endswith(('++', '--')):
            before = before[:-2].rstrip()
            written = re.match(r'\s*;', clean[hit.end():end])
        else:
            written = re.match(r'\s*(?:(?:[-+&|^])?=(?!=)|(?:\+\+|--)\s*;)', clean[hit.end():end])
        if not written or not (before.endswith((';', '{', '}', ')', ':')) or re.search(r'\belse$', before)):
            return None
        writes += 1
    return (kinds.pop(), reads) if writes else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'#|\b(?:asm|__asm__)\b', clean[opening:end]):
        return []
    plans, seen = [], set()
    for decl in _DECL.finditer(clean, opening, end):
        var = decl['name']
        declarations = re.findall(rf'(?:\b(?:[su](?:8|16|32)|int|unsigned|char|short|float|double|f32|f64)|\*)\s+\*?\s*'
                                  rf'{var}\s*[;=,\[]', clean[opening:end])
        if var in seen or len(declarations) != 1 or re.search(rf'(?<![&\w\])])&\s*{var}\b', clean[opening:end]):
            continue
        seen.add(var)
        found = _uses(clean, var, opening + 1, end, decl)
        if found:
            kind, reads = found
            plans.append([(decl.start('type'), decl.end('type'), kind)] + [(a, b, var) for a, b in reads])

    def apply(edits):
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        return text

    out = []
    if len(plans) > 1:
        out.append(apply([edit for plan in plans for edit in plan]))
    out += [apply(plan) for plan in plans]
    return [(FAMILY, text) for text in dict.fromkeys(out) if text != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # registry.py
