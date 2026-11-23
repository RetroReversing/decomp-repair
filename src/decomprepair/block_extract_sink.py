"""A load-and-store scope with other statements inside it, opened after them.

m2c puts the scope of a temporary around everything that was written between the load and its store:

    cameraAngles[0] = yaw;
    {
      f32 pitch = *(f32 *)(marker + 0x38);
      var_s6 = 1;
      sp37 = arg1;
      cameraAngles[1] = pitch;
    }
    temp_s4 = &table + kind * 0xE8;

The game's order was `var_s6 = 1; sp37 = arg1; temp_s4 = ...;` and then the pitch's load and store, so the load of a
float sat after the integer work the first scheduler fills its latency with (KMC GCC 2.7.2: 60 -> 1 in one
557-instruction function; the other half of the same function's difference, a jump table, was the next step).
Neither half is a rewrite by itself, both moves together are the child that paid: the scope's plain assignments go
above it, and the scope (the load and its store, nothing between) goes below the statements that follow it.

A proposal takes a bare block `{ T v = LOAD; A...; W = v; }` whose middle statements `A` are plain assignments to
names (no dereference in the value, none naming `v`) and which is followed, up to the end of its enclosing block, by
plain assignments `F` to names that do not read `v` or the store's base (no dereference in their values either: a
dereference could read what `W` writes). Three children: `A F { T v = LOAD; W = v; }` (both moves), `F {block}` (the
scope sunk alone) and `A {T v = LOAD; W = v;}` (the assignments lifted alone). MIPS only."""
import re

from .csource import find
from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'block_extract_sink'
FAMILIES = (FAMILY,)
LIMIT = 9

_ID = r'[A-Za-z_]\w*'
_TYPE = r'(?:(?:unsigned|signed|const)\s+)*[A-Za-z_]\w*(?:\s*\*+)?'
_DEREF = re.compile(r'(?:^|[^\w)\]])\*|->|\[')


def _statements(clean, start, end):
    """[(a, b)] spans of the `;`-terminated simple statements between start and end, or None when anything else is there."""
    spans, at = [], start
    while at < end:
        if not clean[at:end].strip():
            break
        semicolon = clean.find(';', at, end)
        if semicolon < 0 or any(ch in clean[at:semicolon] for ch in '{}'):
            return None
        spans.append((at, semicolon + 1))
        at = semicolon + 1
    return spans


def _plain(statement):
    """(name, value) of `name = value;` with no dereference or call in the value, else None."""
    hit = re.fullmatch(rf'\s*({_ID})\s*=(?!=)\s*([^;]+);\s*', statement)
    if not hit or _DEREF.search(re.sub(r'\s+', '', hit[2])) or re.search(rf'\b{_ID}\s*\(\s*[^)]*\)', re.sub(r'\([^()]*\)\s*(?=[\w(])', '', hit[2])):
        return None
    return hit[1], hit[2]


def variants(source, name, arch='mips'):
    """Proposals: the plain assignments inside a load-and-store scope lifted out, the scope sunk below what follows."""
    span = find(source, name)
    part = view(source, name) if span and arch == 'mips' else None
    if not part:
        return []
    clean = part.clean
    out = []
    for brace in re.finditer(r'\{', clean[part.opening + 1:part.end - 1]):
        opening = part.opening + 1 + brace.start()
        before = clean[:opening].rstrip()
        if not before or before[-1] not in ';{}':
            continue
        closing = close(clean, opening, '{', '}')
        if not closing:
            continue
        spans = _statements(clean, opening + 1, closing - 1)
        if not spans or len(spans) < 2:
            continue
        first = re.fullmatch(rf'\s*({_TYPE})\s+({_ID})\s*=(?!=)\s*([^;]+);\s*', clean[spans[0][0]:spans[0][1]])
        last = re.fullmatch(rf'\s*([^;=]+?)\s*=(?!=)\s*({_ID})\s*;\s*', clean[spans[-1][0]:spans[-1][1]])
        if not first or not last or last[2] != first[2]:
            continue
        local = first[2]
        middle = spans[1:-1]
        if any(not _plain(clean[a:b]) or re.search(rf'\b{local}\b', clean[a:b]) for a, b in middle):
            continue
        root = re.match(rf'\s*\*?\s*\(*\s*(?:\([^)]*\)\s*)?\(*\s*({_ID})', last[1])
        # the statements after the scope, up to the end of the block that holds it
        stop = opening
        depth = 0
        for at in range(closing, part.end):
            if clean[at] == '{':
                depth += 1
            elif clean[at] == '}':
                if depth == 0:
                    stop = at
                    break
                depth -= 1
        after = (_statements(clean, closing, stop) if stop > opening else None) or []
        taken = []
        for a, b in after:
            plain = _plain(clean[a:b])
            if (not plain or re.search(rf'\b{local}\b', clean[a:b])
                    or (root and re.search(rf'\b{re.escape(root[1])}\b', clean[a:b])) or len(taken) >= 3):
                break
            taken.append((a, b))
        indent = re.search(r'[ \t]*$', source[:opening])[0]
        pad = indent + '  '

        def text(spans_, indent=indent):
            return ''.join(f'\n{indent}' + source[a:b].strip() for a, b in spans_)

        scope_only = (f'\n{indent}{{\n{pad}' + source[spans[0][0]:spans[0][1]].strip()
                      + f'\n{pad}' + source[spans[-1][0]:spans[-1][1]].strip() + f'\n{indent}}}')
        block = source[opening:closing]
        head = source[:opening].rstrip(' \t')
        children = []
        if middle and taken:
            children.append((text(middle) + text(taken) + scope_only, taken[-1][1]))
        if taken:
            children.append((text(taken) + f'\n{indent}' + block, taken[-1][1]))
        if middle:
            children.append((text(middle) + scope_only, closing))
        for body, end_of in children:
            out.append((FAMILY, head + body.lstrip('\n') + source[end_of:]))
        out = [(f, c) for f, c in out if c != source]
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 90}  # the registry: no caller wiring (registry.py)
