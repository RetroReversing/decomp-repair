"""Give one switch arm a separate copy of an immutable incoming byte.

A MIDI handler's key byte feeds several command arms but the note-on arm also
uses it repeatedly across calls. Splitting that arm's reads into a same-type
copy moved a KMC GCC 2.7.2 candidate from 6555 to 6245. The register-allocation
explanation is a hypothesis; the byte comparison is measured on one function.
Only unaddressed byte locals initialized before a plain, non-looping switch
are eligible. The first arm may read the copy only while the local is unchanged.
"""
import re

from .case_temporary_repairs import DECLARATION, _depth_at, _groups, _identifiers, _mentions, _switches
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_value_copy'
FAMILIES = (FAMILY,)
LIMIT = 40


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    if re.search(r"\bgoto\b", clean[opening:end]):
        return []
    switches = _switches(clean, opening, end)
    taken = _identifiers(clean)
    result = []
    for decl in DECLARATION.finditer(clean, opening + 1, end):
        var = decl['name']
        if decl['type'].strip() not in ('u8', 'unsigned char') or _depth_at(clean, opening + 1, decl.start()):
            continue
        mentions = list(_mentions(var).finditer(clean, opening + 1, end))
        if len(re.findall(r'(?m)^[ \t]*[A-Za-z_][\w \t*]*[ \t*]'+re.escape(var)+r'\s*[;=]', clean[opening:end])) != 1:
            continue
        assignment = re.compile(r'(?m)^[ \t]*' + re.escape(var) + r'\s*=(?!=)[^;{}]*;')
        assigns = list(assignment.finditer(clean, decl.end(), end))
        if not assigns:
            continue
        init = assigns[0]
        prior = max(clean.rfind(';', opening, init.start()), clean.rfind('}', opening, init.start()), opening)
        if (re.search(r'\b(?:if|else|for|while|do|switch)\b', clean[prior + 1:init.start()])
                or _depth_at(clean, opening + 1, init.start())
                or _mentions(var).search(clean, clean.find('=', init.start(), init.end()) + 1, init.end())):
            continue
        if re.search(r'&\s*' + re.escape(var) + r'\b', clean[init.end():end]):
            continue
        write = re.compile(r'(?:\+\+\s*|--\s*)' + re.escape(var) + r'\b|\b' + re.escape(var) + r'\s*(?:\+\+|--|[+*/%&|^\-]?=(?!=))')
        if any(m.start() < init.start() for m in mentions if not decl.start() <= m.start() < decl.end()):
            continue
        for body in switches:
            if body[0] <= init.end():
                continue
            switch_at = clean.rfind("switch", init.end(), body[0])
            if switch_at < 0 or _depth_at(clean, opening + 1, switch_at) or re.search(r"\b(?:for|while|do)\b", clean[init.end():switch_at]):
                continue
            nested = [s for s in switches if body[0] < s[0] and s[1] < body[1]]
            groups = _groups(clean, body, nested)
            if not groups or len(groups) < 2:
                continue
            for group_index, (_, a, b) in enumerate(groups):
                if group_index or write.search(clean, init.end(), body[0]) or write.search(clean, a, b):
                    continue
                uses = list(_mentions(var).finditer(clean, a, b))
                if len(uses) < 2 or not any(m.start() < a or m.start() >= b for m in mentions if m.start() >= init.end()):
                    continue
                new = var + '_copy'
                while new in taken:
                    new += '_'
                edits = [(decl.end(), decl.end(), f"{decl['indent']}{decl['type']}{new};\n"),
                         (init.end(), init.end(), f'\n{decl["indent"]}{new} = {var};')]
                edits.extend((m.start(), m.end(), new) for m in uses)
                child = source
                for start, stop, replacement in sorted(edits, reverse=True):
                    child = child[:start] + replacement + child[stop:]
                result.append((FAMILY, child))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
