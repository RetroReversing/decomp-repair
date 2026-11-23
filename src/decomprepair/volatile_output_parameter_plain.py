"""A `volatile` output record that the function only writes, written as a plain pointer.

A search that wanted a function's stores kept in the source's order gave the output pointer `volatile`
(`volatile Segment *out`): every store through it is then a volatile access that the scheduler keeps in place, and the
loads and arithmetic around them stay where the draft put them. A pointer that is only ever stored through has no
reason to be volatile in the original, and the qualifier costs far more than it pins: on a 163-instruction float
function (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) the exact source with `volatile` back on the output pointer
scored 1040 where the plain one matched. `scaffold_strip` and the frame-padding families do not touch a qualifier in the
signature.

`variants` offers, for each `volatile T *name` parameter whose every mention in the body is the target of a store
(`name->field = ...;`, `name[i] = ...;`, `*name = ...;`), the signature without `volatile`. A candidate rewrite; the
exact judge decides, and a parameter that is read, passed on or compared keeps its qualifier.
"""
import re

from .csource import _blank, find

FAMILY = 'volatile_output_parameter_plain'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
PARAMETER = re.compile(rf'\bvolatile(\s+)((?:(?:struct|union|unsigned|signed)\s+)?{IDENT}(?:\s+{IDENT})?\s*)\*(\s*)(?P<name>{IDENT})\s*(?=[,)]|$)')


def _stored_only(body, name):
    mentions = list(re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', body))
    if not mentions:
        return False
    for hit in mentions:
        tail = body[hit.end():]
        if re.match(rf'\s*(?:(?:->|\.)\s*{IDENT}|\[[^\]]*\])(?:\s*(?:(?:->|\.)\s*{IDENT}|\[[^\]]*\]))*\s*=(?!=)', tail):
            continue
        if re.search(r'\*\s*$', body[:hit.start()]) and re.match(r'\s*=(?!=)', tail):
            continue
        return False
    return True


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\(([^{};]*)\)\s*{', clean[span[0]:span[1]])
    if not head:
        return []
    signature = (span[0] + head.start(1), span[0] + head.end(1))
    body = clean[span[0] + head.end():span[1]]
    out = []
    for match in PARAMETER.finditer(clean, *signature):
        if _stored_only(body, match['name']):
            text = source[:match.start()] + source[match.end(1):]
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
