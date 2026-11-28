"""Stage a byte index and slot-table base within one assignment's scope.

A KMC O1 state handler forms several word-slot addresses from byte indices.
Short-lived locals for each index and table base improved a linked diagnostic
from 770 to 530. The generated types preserve the original operands' types;
the exact judge decides each child.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'scoped_byte_slot_index'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic|class|namespace|template|operator)\b|::', context):
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
    index, base = '__repair_scoped_index', '__repair_scoped_base'
    if (macros.intersection(re.findall(IDENT, body)) or {'__typeof__', name, index, base} & macros
            or re.search(rf'\b(?:{index}|{base})\b', clean)):
        return []
    read = (rf'(?P<read>\*\s*\(\s*(?P<table>{IDENT})\s*\+\s*\(\s*\(\s*'
            rf'{IDENT}\s*&\s*0[xX][fF]{{4}}\s*\)\s*\*\s*(?:0[xX]64|100)\s*\)\s*\))')
    pattern = re.compile(rf'(?m)^[ \t]*(?P<stmt>(?P<dest>{IDENT})\s*=\s*\(\s*{read}\s*\*\s*4\s*\)\s*\+\s*(?P<slots>{IDENT})\s*;)')
    sites = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        table, slots = hit['table'], hit['slots']
        if table == slots:
            continue
        # The added block is one statement, even under an unbraced control or label.
        lookup = source[hit.start('read'):hit.end('read')]
        replacement = (f'{{ __typeof__(*{table} + 0) {index}; __typeof__({slots} + 0) {base}; '
                       f'{index} = {lookup}; {base} = {slots}; '
                       f'{hit["dest"]} = ({index} * 4) + {base}; }}')
        sites.append(((hit['dest'], slots), (hit.start('stmt'), hit.end('stmt'), replacement)))
        if len(sites) >= LIMIT:
            break
    result = [(FAMILY, edit(source, [site])) for _, site in sites]
    for key in dict.fromkeys(key for key, _ in sites):
        group = [site for target, site in sites if target == key]
        if len(group) > 1:
            result.append((FAMILY, edit(source, group)))
    if len(sites) > 1:
        result.append((FAMILY, edit(source, [site for _, site in sites])))
    return list(dict.fromkeys(result))


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
