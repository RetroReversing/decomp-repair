"""Products a function uses twice each, computed into locals of their own together, as C written by hand had them.

C borrowed from another release of an SDK routine wrote `bc - (x * sine)` and `bc + (x * sine)` where the routine the
game linked had `xs = x * sine; ys = y * sine; zs = z * sine;` together, before its stores: an N64 matrix builder was
93.8% with the products inline, 92.7% with each local just before its own first use, and exact with the three
computed together right after the call before them. The products are of two plain names of one declared type; the
locals go together at each of the few statement boundaries before the first use, never above a write to an operand.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_product_local'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
PRODUCT = re.compile(r'\(\s*(' + IDENT + r')\s*\*\s*(' + IDENT + r')\s*\)')
TYPES = r'(?:float|f32|double|f64|int|s32|u32|unsigned\s+int)'
REACH = 4


def _declared_type(signature, body, name):
    """The declared type of `name`: one parameter, or one local declaration's list of names (`float ab, bc, t;`)."""
    inside = signature[signature.find('(') + 1:signature.rfind(')')]
    pieces = [piece for piece in inside.split(',')] + [piece for piece in body.split(';')]
    for piece in pieces:
        m = re.match(r'\s*(?:static\s+|register\s+)?(' + TYPES + r')\s+(.*)$', piece.strip().lstrip('{').strip(), re.S)
        if not m:
            continue
        names = re.findall(r'(?:^|,)\s*\**\s*(' + IDENT + r')', m[2])
        if name in names:
            return ' '.join(m[1].split())
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    signature = clean[span[0]:opening]
    counts = {}
    for m in PRODUCT.finditer(body):
        counts.setdefault((m[1], m[2]), []).append(m)
    products = [(pair, hits) for pair, hits in counts.items() if len(hits) >= 2 and pair[0] != pair[1]]
    if not products:
        return []
    kinds = set()
    for (a, b), _ in products:
        ta = _declared_type(signature, body, a)
        tb = _declared_type(signature, body, b)
        if ta is None or ta != tb:
            return []
        kinds.add(ta)
    if len(kinds) != 1:
        return []
    kind = kinds.pop()
    used = set(re.findall(IDENT, body))
    names = []
    for (a, b), _ in products:
        local = '__repair_' + a + '_' + b
        if local in used:
            return []
        names.append(local)
    first = min(h.start() for _, hits in products for h in hits)
    # statement boundaries before the first use, nearest first; stop above any write to an operand
    operands = {x for (a, b), _ in products for x in (a, b)}
    write = re.compile(r'(?<![\w.>])(?:' + '|'.join(map(re.escape, operands)) + r')\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|&\s*(?:'
                       + '|'.join(map(re.escape, operands)) + r')\b|(?:\+\+|--)\s*(?:' + '|'.join(map(re.escape, operands))
                       + r')\b')
    boundaries = []
    pos = body.rfind(';', 0, first)
    while pos > 0 and len(boundaries) < REACH:
        line_end = body.find('\n', pos) + 1
        boundaries.append(line_end)
        previous = body.rfind(';', 0, pos)
        statement = body[previous + 1 if previous >= 0 else 1:pos + 1]
        if write.search(statement) or re.search(r'[{}]', statement):
            break
        pos = previous
    if not boundaries:
        return []
    line_start = body.rfind('\n', 0, first) + 1
    indent = re.match(r'[ \t]*', body[line_start:])[0]
    declaration_at = body.find('\n', 1) + 1  # after the opening brace's line
    result = []
    for at in boundaries:
        text = source[:opening] + source[opening:end]
        # replace uses from the end so offsets hold
        uses = sorted(((h, local) for ((_, hits), local) in zip(products, names) for h in hits),
                      key=lambda p: -p[0].start())
        rel = text[opening:]
        for h, local in uses:
            rel = rel[:h.start()] + local + rel[h.end():]
        assignments = ''.join(f'{indent}{local} = {a} * {b};\n' for ((a, b), _), local in zip(products, names))
        shift = sum(len(local) - (h.end() - h.start()) for h, local in uses if h.start() < at)
        rel = rel[:at + shift] + assignments + rel[at + shift:]
        rel = rel[:declaration_at] + ''.join(f'{indent}{kind} {local};\n' for local in names) + rel[declaration_at:]
        candidate = text[:opening] + rel + source[end:]
        if candidate != source and candidate not in [c for _, c in result]:
            result.append((FAMILY, candidate))
    return result
