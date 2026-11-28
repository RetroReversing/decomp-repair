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
[(family, source)].

A read that is a whole argument at a position the callee's prototype declares `T` converts the same way without a
written cast (`angle = next(); sine(angle);` with `s16 sine(s16);`), and a literal initialiser that fits `T` keeps
its value, so both are taken too. On a 204-instruction N64 collision handler (SN GCC 2.8.1 `-G0 -mips3 -O2`) an
`s32 angle = 0;` carried round a loop and only passed to two `s16` parameters, declared `s16`, took 940 -> 865: it
changed which of two saved registers the angle and the loop counter got."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'cast_reads_narrow'
FAMILIES = (FAMILY,)
LIMIT = 6
_DECL = re.compile(r'(?<=[;{}])(?P<space>\s*)(?P<type>s32|u32|int|signed\s+int|unsigned\s+int|unsigned)\s+'
                   r'(?P<name>[A-Za-z_]\w*)\s*(?:=\s*(?P<init>-?(?:0[xX][0-9a-fA-F]+|[0-9]+))\s*)?;')
_CAST = r'\(\s*(?P<cast>s16|u16|s8|u8)\s*\)\s*'
_RANGE = {'s8': (-128, 127), 'u8': (0, 255), 's16': (-32768, 32767), 'u16': (0, 65535)}
_ARGUMENT = re.compile(r'(?<![\w.>])([A-Za-z_]\w*)\s*\(([^(){};]*)\)')


def _parameter_reads(clean, context, var, start, end):
    """(type, start, end) of each bare `var` that is a whole argument at a narrow parameter of a prototype."""
    found = []
    for call in _ARGUMENT.finditer(clean, start, end):
        at = call.start(2)
        for position, argument in enumerate(call[2].split(',')):
            if argument.strip() == var:
                prototype = re.search(rf'\b{call[1]}\s*\(([^(){{}};]*)\)\s*;', context)
                parameters = prototype[1].split(',') if prototype else []
                kind = re.match(r'\s*(s16|u16|s8|u8)(?:\s+[A-Za-z_]\w*)?\s*$', parameters[position]) \
                    if position < len(parameters) else None
                if kind:
                    begin = at + len(argument) - len(argument.lstrip())
                    found.append((kind[1], begin, begin + len(var)))
            at += len(argument) + 1
    return found


def _uses(clean, context, var, start, end, decl):
    """(kind, [(start, end) of each cast read]) when every use of `var` allows the narrow type, else None."""
    kinds, reads, writes, taken = set(), [], 0, []
    for hit in re.finditer(rf'{_CAST}{var}\b(?!\s*(?:\[|\.|->|\+\+|--|\(|(?:<<|>>|[-+*/%&|^])?=(?!=)))', clean[:end]):
        if hit.start() >= start:
            kinds.add(hit['cast'])
            reads.append((hit.start(), hit.end()))
            taken.append((hit.start(), hit.end()))
    for kind, a, b in _parameter_reads(clean, context, var, start, end):
        if not any(x <= a < y for x, y in taken):
            kinds.add(kind)
            taken.append((a, b))
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
    kind = kinds.pop()
    low, high = _RANGE[kind]
    if decl['init'] is not None and not low <= int(decl['init'], 0) <= high:
        return None
    return (kind, reads) if writes else None


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'#|\b(?:asm|__asm__)\b', clean[opening:end]):
        return []
    context = _blank(header or '') + '\n' + clean
    plans, seen = [], set()
    for decl in _DECL.finditer(clean, opening, end):
        var = decl['name']
        declarations = re.findall(rf'(?:\b(?:[su](?:8|16|32)|int|unsigned|char|short|float|double|f32|f64)|\*)\s+\*?\s*'
                                  rf'{var}\s*[;=,\[]', clean[opening:end])
        if var in seen or len(declarations) != 1 or re.search(rf'(?<![&\w\])])&\s*{var}\b', clean[opening:end]):
            continue
        seen.add(var)
        found = _uses(clean, context, var, opening + 1, end, decl)
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


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 95}  # registry.py
