"""A local that only mirrors another variable, written as that variable.

A list walk written with two names, the cursor the walk steps and a wider "index" copy of it (`next = T[cur].next;
cur = next;` or `next = T[at].next; at = next & 0xFFFF;`), is m2c's reading of a target that zero-extends the walking
`u16` for its table index. The game indexed with the walking variable itself and the compiler made the extension: at
KMC gcc 2.7.2 -O1 the copy left the entry test's `andi $v0, $a0, 0xffff; move $a1, $v0` unreachable in every
spelling (275 on a 105-instruction list splice), and `T[arg0]` gave it (275 -> 5 with the loops as `while`).

When every assignment to a local `M` is `M = P;` (or `M = P & 0xFFFF;`, `(u16) P`) of one other variable `P` that is
at least as narrow, and every other write of `P` is followed at once by such an assignment, `M` always holds `P`:
its reads become `P` and the assignments and declaration go. A second child also writes each
`if (c) { do { .. } while (c); }` left with one condition as `while (c) { .. }`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'mirror_local_drop'
FAMILIES = (FAMILY,)
LIMIT = 6

_WIDTH = {'u8': 8, 'u16': 16, 'u32': 32, 's32': 32, 'int': 32}
_DECL = re.compile(rf'(?<=[;{{}}])[ \t]*\n?[ \t]*(?P<type>u8|u16|u32|s32|int)[ \t]+(?P<name>{IDENT})[ \t]*;')


def _types(part, source, name):
    """The plain unsigned or word scalars of the function: its parameters and locals."""
    head = part.clean[:part.opening]
    start = head.rfind(name)
    found = {}
    for hit in re.finditer(rf'[(,]\s*(u8|u16|u32|s32|int)\s+({IDENT})\s*(?=[,)])', head[start:]):
        found[hit[2]] = hit[1]
    locals_ = {hit['name']: hit for hit in _DECL.finditer(part.clean, part.opening, part.end)}
    found.update({key: hit['type'] for key, hit in locals_.items()})
    return found, locals_


def _drop(source, part, mirror, declaration, types):
    body, opening, end = part.clean, part.opening, part.end
    word = re.escape(mirror)
    if (len(re.findall(rf'\b{word}\b', body[opening:declaration.start()]))
            or re.search(rf'(?<!&)&\s*{word}\b|(?:\+\+|--)\s*{word}\b|\b{word}\s*(?:\+\+|--)'
                         rf'|\b{word}\s*(?:[-+*/%&|^]|<<|>>)=|(?:\.|->)\s*{word}\b', body[opening:end])):
        return None
    writes = list(re.finditer(rf'(?<![.>\w]){word}\s*=(?!=)\s*(?P<value>[^;{{}}]+);', body[opening:end]))
    if not writes or len(re.findall(rf'(?<![.>\w]){word}\s*=(?!=)', body[opening:end])) != len(writes):
        return None
    sources, spans = set(), []
    for hit in writes:
        value = re.fullmatch(rf'\s*(?:\(\s*u16\s*\)\s*(?P<cast>{IDENT})|(?P<plain>{IDENT})'
                             rf'(?P<mask>\s*&\s*0xFFFF)?)\s*', hit['value'])
        if not value:
            return None
        origin = value['cast'] or value['plain']
        if (value['cast'] or value['mask']) and types.get(origin) != 'u16':
            return None
        sources.add(origin)
        at = opening + hit.start()
        if body[:at].rstrip()[-1:] not in ';{}':
            return None
        spans.append((at, opening + hit.end()))
    if len(sources) != 1:
        return None
    origin = sources.pop()
    narrow, wide = _WIDTH.get(types.get(origin)), _WIDTH[types[mirror]]
    if origin == mirror or narrow is None or not (types[origin] == types[mirror] or narrow < wide):
        return None
    other = re.escape(origin)
    if re.search(rf'(?<!&)&\s*{other}\b|(?:\+\+|--)\s*{other}\b|\b{other}\s*(?:\+\+|--)'
                 rf'|\b{other}\s*(?:[-+*/%&|^]|<<|>>)=', body[opening:end]):
        return None
    for hit in re.finditer(rf'(?<![.>\w]){other}\s*=(?!=)[^;{{}}]*;', body[opening:end]):
        following = body[opening + hit.end():end]
        gap = len(following) - len(following.lstrip())
        if opening + hit.end() + gap not in [start for start, _ in spans]:
            return None
    edits = []
    for start, stop in [*spans, (declaration.start(), declaration.end())]:
        line = source.rfind('\n', 0, start)
        if line >= 0 and not source[line + 1:start].strip():
            start = line
        edits.append((start, stop, ''))
    for hit in re.finditer(rf'(?<![.>\w]){word}\b', body[opening:end]):
        at = opening + hit.start()
        if not any(start <= at < stop for start, stop, _ in edits):
            edits.append((at, at + len(mirror), origin))
    return edit(source, edits)


def _closing(text, opening):
    depth = 0
    for at in range(opening, len(text)):
        if text[at] == '{':
            depth += 1
        elif text[at] == '}':
            depth -= 1
            if not depth:
                return at
    return -1


def _guarded_loops(source, name):
    """Every `if (c) { do { .. } while (c); }` as `while (c) { .. }`."""
    changed = source
    for _ in range(LIMIT):
        part = view(changed, name)
        if not part:
            break
        clean = part.clean
        for hit in re.finditer(r'\bif\s*\((?P<condition>[^{};]+)\)\s*\{\s*do\s*(?=\{)', clean):
            inner = hit.end()
            close = _closing(clean, inner)
            tail = re.compile(r'\s*while\s*\((?P<condition>[^{};]+)\)\s*;\s*\}').match(clean, close + 1)
            if close < 0 or not tail:
                continue
            first = changed[hit.start('condition'):hit.end('condition')]
            second = changed[tail.start('condition'):tail.end('condition')]
            if ''.join(first.split()) != ''.join(second.split()):
                continue
            changed = changed[:hit.start()] + f'while ({first}) ' + changed[inner:close + 1] + changed[tail.end():]
            break
        else:
            break
    return changed


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    types, locals_ = _types(part, source, name)
    out = []
    for mirror, declaration in list(locals_.items())[:40]:
        text = _drop(source, part, mirror, declaration, types)
        if not text:
            continue
        out.append(text)
        looped = _guarded_loops(text, name)
        if looped != text:
            out.insert(0, looped)
        if len(out) >= LIMIT:
            break
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
