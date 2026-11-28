"""A switch-like `if` ladder m2c read back with shared stores behind labels, written as compound updates per arm.

A field copied from a source and then advanced by a different amount per mode,

    p->angle = from->angle;
    if (mode == 0) { p->angle += A; p->spread = a; } else if (mode == 1) { p->angle += B; p->spread = b; } ...

is cross-jumped by the compiler into one store of each field at a shared place, which m2c reads back as

    p->angle = t;
    if (mode == 0) { p->angle = t + A; v = a; goto block; }
    if (mode != 1) { if (mode == 2) { ... goto block; } } else { p->angle = t + B; v = b; block: p->spread = v; }

Four rewrites are each no better alone, so the child makes them together, on every ladder of the function: each `goto`
gets its own copy of the shared tail (`goto_paths_written_out`), every nested `!=` level is turned into `else if`
(`inverted_guard_ladder`'s turn), a scratch local only ever set right before the one store that reads it is written into
that store, and an arm's `place = t + K;` (or `place = place + K;`) after `place = t;` becomes `place += K;`. On a
267-instruction N64 spawner (SN GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`) with two such ladders the four together took the
otherwise exact source from 905 to 0; the `!=` form alone scored 640, `t + K` stores alone 1110 and the scratch local
alone 955. The compound step runs only where nothing between `place = t;` and an arm can change `t` or the place: plain
stores through the same pointer at other places, conditions without calls or assignments. The judge decides."""
import re

from . import goto_paths_written_out, inverted_guard_ladder
from .csource import _blank, find
from .goto_structure_repairs import parse
from .integer_repair_support import IDENT, edit, view

FAMILY = 'shared_store_ladder'
FAMILIES = (FAMILY,)

_TURNS = 8
_LITERAL = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?'
_PLACE = r'(?:\(\([^;={}\n]*?\)->\w+|M2C_FIELD\([^;={}\n]*?\)|[A-Za-z_]\w*(?:(?:->|\.)\w+)+)'
_PAIR = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?P<v>{IDENT}) = (?P<e>[^;={{}}\n]+);\n'
                   rf'(?P<ind2>[ \t]*)(?P<place>{_PLACE}) = (?P=v);\n')
_WIDE = r'(?:s32|u32|int|long)'
_CALL = re.compile(r'(?<![\w.])(?!(?:if|sizeof|M2C_FIELD)\b)[A-Za-z_]\w*\s*\(')
_INITIAL = re.compile(rf'(?m)^[ \t]*(?P<place>{_PLACE}) = (?P<t>{IDENT});\n'
                      r'(?P<between>(?:[ \t]*[^;{}\n]+ = [^;{}()\n]+;\n|[ \t]*M2C_FIELD\([^;{}\n]*\) = [^;{}()\n]+;\n)*)'
                      r'(?P<ind>[ \t]*)(?=if \()')


def _inline_scratch(source, name):
    """`v = e; place = v;` -> `place = e;`, for a local with no other use than such pairs."""
    part = view(source, name)
    if not part:
        return source
    body = part.clean[part.opening:part.end]
    pairs = list(_PAIR.finditer(part.clean, part.opening, part.end))
    spans = []
    for local in dict.fromkeys(hit['v'] for hit in pairs):
        mine = [hit for hit in pairs if hit['v'] == local]
        declared = re.search(rf'(?m)^[ \t]*(?P<type>\w+) {local};\n', body)
        if not declared or len(re.findall(rf'\b{local}\b', body)) != 2 * len(mine) + 1:
            continue
        wide = re.fullmatch(_WIDE, declared['type'])
        # a narrow local truncates: only a small literal goes through it unchanged
        if not wide and not all(re.fullmatch(_LITERAL, h['e']) and int(h['e'].rstrip('uU'), 0) < 0x80 for h in mine):
            continue
        for hit in mine:
            value = source[hit.start('e'):hit.end('e')]
            place = source[hit.start('place'):hit.end('place')]
            spans.append((hit.start(), hit.end(), f'{hit["ind"]}{place} = {value};\n'))
        at = part.opening + declared.start()
        spans.append((at, part.opening + declared.end(), ''))
    return edit(source, spans) if spans else source


def _base(place):
    found = re.search(r'->|M2C_FIELD\(', place)
    head = place[:found.start()] if found and found.group() == '->' else place[found.end():] if found else place
    return (re.findall(IDENT, head) or [''])[-1 if found and found.group() == '->' else 0]


def _statements(stmts):
    for stmt in stmts:
        yield stmt
        for key in ('then', 'other', 'body'):
            part = stmt.parts.get(key)
            if part:
                yield from _statements(part['stmts'])


def _compound(source, name):
    """`place = t; ... if (..) { place = t + K; }` -> `place += K;` in every arm."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    try:
        tree = list(_statements(parse(clean, part.opening + 1, clean.rfind("}", part.opening, part.end + 1))))
    except (ValueError, RecursionError):
        return source
    ifs = {stmt.start: stmt for stmt in tree if stmt.kind == 'if'}
    spans = []
    for hit in _INITIAL.finditer(clean, part.opening, part.end):
        stmt = ifs.get(hit.end())
        if not stmt:
            continue
        place, value = source[hit.start('place'):hit.end('place')], hit['t']
        base = _base(place)
        written = [line.split(' = ', 1)[0].strip() for line in hit['between'].splitlines()]
        if any(w in (value, base, place) or _base(w) != base for w in written):
            continue
        ladder = clean[stmt.start:stmt.end]
        conditions = re.findall(r'\bif \(([^{}]*)\) \{', ladder)
        if any(re.search(r'\w\s*\(|(?<![=!<>])=(?!=)|\+\+|--', c) for c in conditions):
            continue
        if _CALL.search(ladder) or re.search(r'\b(?:for|while|do|switch|goto)\b|\+\+|--', ladder):
            continue
        update = re.compile(rf'(?P<lhs>{re.escape(place)}) = (?:\({_WIDE}\) )?\(?(?:{re.escape(value)}|{re.escape(place)})'
                            rf' (?P<op>[-+]) (?P<k>{_LITERAL})\)?;')
        arms = list(update.finditer(source, stmt.start, stmt.end))
        # one write of the place per arm, and none of the copied value
        writes = len(re.findall(rf'{re.escape(place)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', source[stmt.start:stmt.end]))
        apart = all(re.search(r'\belse\b', clean[a.end():b.start()]) for a, b in zip(arms, arms[1:]))
        if not arms or writes != len(arms) or not apart or re.search(
                rf'\b{re.escape(value)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', ladder):
            continue
        spans += [(a.start(), a.end(), f'{place} {a["op"]}= {a["k"]};') for a in arms]
    return edit(source, spans) if spans else source


def variants(source, name):
    if not find(source, name):
        return []
    text = source
    if re.search(r'\bgoto\b', _blank(source)):
        written = goto_paths_written_out.variants(source, name)
        if not written:
            return []
        text = written[0][1]
    for _ in range(_TURNS):
        turned = inverted_guard_ladder._flatten(text, name)
        if turned is None:
            break
        text = turned
    scratch = _inline_scratch(text, name)
    done = _compound(scratch, name)
    if done == scratch:
        return []  # no ladder that updates an earlier store: the single rewrites cover the rest
    return [(FAMILY, done)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 500}
