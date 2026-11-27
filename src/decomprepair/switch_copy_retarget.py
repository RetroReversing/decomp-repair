"""Move a byte copy's reads from one switch case to another.

A MIPS command handler uses the same incoming byte in several cases. Moving
its copy from the note-on case to a later pressure case changed a KMC GCC
2.7.2 score from 2825 to 2745. The register-allocation explanation is a
hypothesis. Only top-level same-type local copies, with no intervening writes,
addresses, gotos or fallthrough into the new case, are offered.
"""
import re

from .case_temporary_repairs import DECLARATION, _depth_at, _groups, _mentions, _switches
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_copy_retarget'
FAMILIES = (FAMILY,)


def _writes(var):
    return re.compile(r'(?:\+\+\s*|--\s*)\b' + re.escape(var) + r'\b|\b' + re.escape(var) + r'\s*(?:\+\+|--|[+*/%&|^\-]?=(?!=))')


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:goto|volatile)\b', clean[opening:end]):
        return []
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+u8\b|\btypedef\b[^;]*\bvolatile\b[^;]*\bu8\s*;', context):
        return []
    declarations = list(DECLARATION.finditer(clean, opening + 1, end))
    names = {m['name']: m for m in declarations if _depth_at(clean, opening + 1, m.start()) == 0
             and m['type'].strip() in ('u8', 'unsigned char')}
    result = []
    for copy in names:
        for assignment in re.finditer(r'(?m)^[ \t]*' + re.escape(copy) + r'\s*=\s*(' + r'[A-Za-z_]\w*' + r')\s*;', clean[opening:end]):
            a, b = opening + assignment.start(), opening + assignment.end()
            original = assignment[1]
            if original == copy or original not in names or _depth_at(clean, opening + 1, a):
                continue
            if sum(m['name'] == copy for m in declarations) != 1 or sum(m['name'] == original for m in declarations) != 1:
                continue
            if any(re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(v) + r'\b', context) or
                   len(re.findall(r'(?m)(?:^|[;{}])[ \t]*[A-Za-z_][\w \t*]*[ \t*]' + re.escape(v) + r'\s*[;=]', clean[opening:end])) != 1
                   for v in (copy, original)):
                continue
            if re.search(r'&\s*(?:' + re.escape(copy) + '|' + re.escape(original) + r')\b', clean[opening:end]):
                continue
            if _writes(copy).search(clean, b, end):
                continue
            switches = _switches(clean, opening, end)
            for body in switches:
                if body[0] <= b or _writes(original).search(clean, b, body[0]):
                    continue
                switch_at = clean.rfind('switch', b, body[0])
                if switch_at < 0 or _depth_at(clean, opening + 1, switch_at) or re.search(r'\b(?:for|while|do)\b', clean[b:switch_at]):
                    continue
                nested = [s for s in switches if body[0] < s[0] and s[1] < body[1]]
                groups = _groups(clean, body, nested)
                if not groups:
                    continue
                copy_uses = list(_mentions(copy).finditer(clean, b, end))
                old = [(j, g) for j, g in enumerate(groups) if any(g[1] <= x.start() < g[2] for x in copy_uses)]
                if len(old) != 1 or any(not (old[0][1][1] <= x.start() < old[0][1][2]) for x in copy_uses):
                    continue
                oi, (_, oa, ob) = old[0]
                if _writes(original).search(clean, oa, ob):
                    continue
                for ni, (_, na, nb) in enumerate(groups):
                    if ni == oi or _writes(original).search(clean, na, nb):
                        continue
                    if ni:
                        _, pa, pb = groups[ni - 1]
                        if not re.search(r'(?:^|[;}])\s*(?:break|return(?:\s+[^;{}]+)?)\s*;\s*$', clean[pa:pb]):
                            continue
                    uses = list(_mentions(original).finditer(clean, na, nb))
                    if not uses:
                        continue
                    edits = [(m.start(), m.end(), original) for m in copy_uses]
                    edits.extend((m.start(), m.end(), copy) for m in uses)
                    child = source
                    for start, stop, replacement in sorted(edits, reverse=True):
                        child = child[:start] + replacement + child[stop:]
                    result.append((FAMILY, child))
                    if len(result) >= 24:
                        return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 40}
