"""A float difference, and its reciprocal, written back into the parameter they were computed from.

    d = x1 - x0;                     x1 = x1 - x0;
    if (d == 0.0f) { ... }    ->     if (x1 == 0.0f) { ... }
    r = 1.0f / d;                    x1 = 1.0f / x1;

m2c gives every value a temporary of its own. The target of an N64 interpolation (GCC 2.7.2 `-O1`) loaded two stack
parameters straight into the registers of their differences and divided them in place: the parameters were reused. One
at a time each reuse moved the score the wrong way or not at all; all of them with `shared_return_hoist` reached 0.

param_difference_reuse
    Float parameters p not named after the statement `t = p - q;` (t an `f32`/`float` local assigned only there):
    t is renamed to p. Then every `u = 1.0f / v;` (u such a local, v not named after it) renames u to v. Children: the
    differences alone, with the reciprocals, and both again on each `shared_return_hoist` child; each of those also with
    `tile_arm_chains.shared_return_split` (the arm that jumps to a shared `return` returns on its own), which was the
    last step of the match.
"""
import re

from . import shared_return_hoist, tile_arm_chains
from .integer_repair_support import IDENT, view

FAMILY = 'param_difference_reuse'
FAMILIES = (FAMILY,)
LIMIT = 8
FLOAT = r'(?:f32|float)'
DIFFERENCE = re.compile(rf'(?m)^[ \t]*(?P<t>{IDENT})\s*=\s*(?P<p>{IDENT})\s*-\s*{IDENT}\s*;')
RECIPROCAL = re.compile(rf'(?m)^[ \t]*(?P<u>{IDENT})\s*=\s*1(?:\.0*)?f?\s*/\s*(?P<v>{IDENT})\s*;')


def _parameters(part, name):
    head = re.findall(rf'\b{re.escape(name)}\s*\(([^(){{}};]*)\)\s*\{{', part.clean[:part.opening + 1])
    return set(re.findall(rf'(?:^|,)\s*{FLOAT}\s+({IDENT})\s*(?=,|$)', head[-1])) if head else set()


def _step(source, name, pattern, new_name, old_name, sources):
    """Rename the first qualifying local; None when none qualifies."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    body = clean[part.opening:part.end]
    if re.search(r'\b(?:for|while|do)\b|&\s*[A-Za-z_]', body.replace('&&', '  ')):
        return None
    for hit in pattern.finditer(clean, part.opening, part.end):
        local, target = hit[old_name], hit[new_name]
        declaration = re.search(rf'(?m)^[ \t]*{FLOAT}\s+{re.escape(local)}\s*;\n?', clean[part.opening:part.end])
        if local == target or not declaration or not sources(part, target):
            continue
        if len(re.findall(rf'\b{re.escape(local)}\b\s*(?:[-+*/]?=(?!=)|\+\+|--)', body)) != 1:
            continue
        if re.search(rf'\b{re.escape(target)}\b', clean[hit.end():part.end]):
            continue
        start = part.opening + declaration.start()
        stop = part.opening + declaration.end()
        text = source[:start] + source[stop:]
        head, tail = text[:part.opening], text[part.opening:]
        return head + re.sub(rf'(?<![.>\w]){re.escape(local)}\b', target, tail)
    return None


def _repeat(source, name, pattern, new_name, old_name, sources):
    for _ in range(12):
        changed = _step(source, name, pattern, new_name, old_name, sources)
        if changed is None:
            break
        source = changed
    return source


def _reused(source, name):
    part = view(source, name)
    if not part:
        return []
    parameters = _parameters(part, name)
    differences = _repeat(source, name, DIFFERENCE, 'p', 't', lambda _, target: target in parameters)

    def known(current, target):
        return target in _parameters(current, name) or bool(
            re.search(rf'(?m)^[ \t]*{FLOAT}\s+{re.escape(target)}\s*;', current.clean[current.opening:current.end]))

    both = _repeat(differences, name, RECIPROCAL, 'v', 'u', known)
    return [text for text in (both, differences) if text != source]


def variants(source, name):
    out = []
    for base in [text for _, text in shared_return_hoist.variants(source, name)] + [source]:
        for text in _reused(base, name):
            # the split's children first: they are the furthest combination
            for child in [*tile_arm_chains.shared_return_split(text, name), text]:
                if (FAMILY, child) not in out:
                    out.append((FAMILY, child))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # registry: no wiring
