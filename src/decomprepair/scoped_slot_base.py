"""Hold a byte-array address in a local at a scaled slot assignment.

In a KMC O1 state handler, two pointer assignments add a scaled byte index
to the same table. A short-lived base local at each site improved a linked
diagnostic from 810 to 770. The pointer retains the table's own type and
byte arithmetic; the judge decides each child.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'scoped_slot_base'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'\b(?:class|namespace|template|operator)\b|::', context):
        return []  # C++ overloads can make these apparent scalar operations observable
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    local = '__repair_site_base'
    if macros.intersection(re.findall(IDENT, body)) or {'__typeof__', name, local} & macros or re.search(rf'\b{local}\b', clean):
        return []
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if not signatures:
        return []
    signature = signatures[-1].start()
    pattern = re.compile(rf'(?m)^[ \t]*(?P<stmt>(?P<dest>{IDENT})\s*=\s*\(\s*(?P<index>{IDENT})\s*\*\s*4\s*\)\s*\+\s*(?P<table>{IDENT})\s*;)')
    sites = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        table = hit['table']
        if not re.search(rf'\bextern\s+char\s+{re.escape(table)}\s*\[\s*\]\s*;', _blank(context)):
            continue
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+){re.escape(table)}\s*(?:[;=,\[)]|$)')
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*{re.escape(table)}\s*(?:[;=,\[])'
        if re.search(shadow, clean[signature:part.end]) or re.search(multi, clean[signature:part.end]):
            continue
        replacement = (f'{{ __typeof__({table} + 0) {local}; {local} = {table}; '
                       f'{hit["dest"]} = {local} + ({hit["index"]} * 4); }}')
        sites.append(((hit['dest'], table), (hit.start('stmt'), hit.end('stmt'), replacement)))
        if len(sites) >= LIMIT:
            break
    result = [(FAMILY, edit(source, [site])) for _, site in sites]
    for key in dict.fromkeys(key for key, _ in sites):
        group = [site for target, site in sites if target == key]
        if len(group) > 1:
            result.append((FAMILY, edit(source, group)))
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
