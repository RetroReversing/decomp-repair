"""Reuse a dead pointer for the first store after a non-null guard."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'guarded_pointer_copy'
_GUARD = re.compile(rf'\bif\s*\(\s*({IDENT})\s*!=\s*(?:0|NULL)\s*\)\s*\{{')
_LOCAL = re.compile(rf'(?m)^[ \t]*(?P<type>{IDENT}\s*\*)\s*(?P<name>{IDENT})\s*;')
_STORE = re.compile(r'(?m)^[ \t]*\*[^;{}\n]+?\s*=(?!=)[^;{}\n]+;')


def _escaped(body, name):
    return (len(re.findall(rf'\b{IDENT}\s*\*+\s*{name}\s*(?=[;=,\[])', body)) != 1
            or re.search(rf'(?<!&)&(?!&)\s*(?:\(\s*)*{name}\b', body))


def variants(source, name, header='', arch=None):
    if arch not in (None, 'mips'):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start = clean.find('{', *span)
    if start < 0:
        return []
    body = clean[start:span[1]]
    locals_ = [decl for decl in _LOCAL.finditer(body) if body.count('{', 0, decl.start()) ==
               body.count('}', 0, decl.start()) + 1]
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')', _blank(header) + '\n' + clean))
    result = []
    for guard in _GUARD.finditer(body):
        origin = guard[1]
        origin_decls = [decl for decl in locals_ if decl['name'] == origin and decl.start() < guard.start()]
        if len(origin_decls) != 1 or origin in macros or _escaped(body, origin):
            continue
        typ = ''.join(origin_decls[0]['type'].split())
        first = guard.end()
        end = close(body, first - 1, '{', '}')
        if end is None:
            continue
        region = body[first:end - 1]
        # A label or transfer could bypass the copy or carry the changed local
        # out of the region before its next assignment.
        if re.search(rf'\b(?:goto|break|continue|return|case|default)\b|(?m:(?:^|[;{{}}:])\s*{IDENT}\s*:)', region):
            continue
        for store in _STORE.finditer(region):
            prefix = region[:store.start()]
            if prefix.count('{') != prefix.count('}') or re.search(rf'\b{origin}\b', prefix):
                continue
            lhs = store[0].split('=', 1)[0]
            refs = list(re.finditer(rf'\b{origin}\b', lhs))
            if len(refs) != 1:
                continue
            ref = first + store.start() + refs[0].start()
            for decl in locals_:
                dest = decl['name']
                if (dest == origin or dest in macros or decl.start() >= guard.start()
                        or ''.join(decl['type'].split()) != typ):
                    continue
                if _escaped(body, dest):
                    continue
                uses = list(re.finditer(rf'\b{dest}\b', region))
                if not uses:
                    continue
                overwrite = uses[0]
                before = region[:overwrite.start()]
                if (overwrite.start() < store.end() or before.count('{') != before.count('}')
                        or before[before.rfind('\n') + 1:].strip()
                        or not before.rstrip().endswith((';', '}'))):
                    continue
                assignment = re.match(r'\s*=(?!=)\s*([^;{}]+);', region[overwrite.end():])
                if not assignment or re.search(rf'\b{dest}\b', assignment[1]):
                    continue
                if macros.intersection(re.findall(IDENT, before)):
                    continue
                content = source[start + first:start + end - 1]
                indent = re.match(r'\n([ \t]+)\S', content)
                if not indent:
                    continue
                insert = start + first + 1
                candidate = edit(source, [
                    (insert, insert, f'{indent[1]}{dest} = {origin};\n'),
                    (start + ref, start + ref + len(origin), dest),
                ])
                result.append((FAMILY, candidate))
                if len(result) == 4:
                    return result
    return result
