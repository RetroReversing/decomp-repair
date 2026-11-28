"""Stage a byte index used to address word slots in a byte array.

In a KMC O1 state handler two pointer assignments read a byte index, scale it
by four, and add a word-slot table's byte address. Staging the byte in one word
local at both sites improved a linked diagnostic from 1160 to 810. Each read
stays at its original site; the judge decides each child.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_slot_index_stage'
LIMIT = 6


def _entry(clean, body_start, start):
    """Whether inserting another statement here preserves any enclosing control."""
    prefix = clean[body_start:start].rstrip()
    if not prefix or prefix[-1] in ';{}':
        return True
    label = re.search(rf'\b{IDENT}\s*:(?!:)\s*$', prefix)
    if not label or label[0].strip().startswith(('case ', 'default:')):
        return False
    return prefix[:label.start()].rstrip()[-1:] in ('', ';', '{', '}')


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic|__LINE__)\b', context):
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
    local = '__repair_slot_index'
    if macros.intersection(re.findall(IDENT, body)) or {'__typeof__', name, local} & macros or re.search(rf'\b{local}\b', clean):
        return []
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if not signatures:
        return []
    signature = signatures[-1].start()
    expression = (rf'(?P<read>\*\s*\(\s*(?P<table>{IDENT})\s*\+\s*\(\s*\(\s*'
                  rf'(?P<arg>{IDENT})\s*&\s*0[xX][fF]{{4}}\s*\)\s*\*\s*(?:0[xX]64|100)\s*\)\s*\))')
    pattern = re.compile(rf'(?m)^[ \t]*(?P<statement>(?P<dest>{IDENT})\s*=\s*\(\s*{expression}\s*\*\s*4\s*\)\s*\+\s*(?P<slots>{IDENT})\s*;)')
    sites = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        table, slots = hit['table'], hit['slots']
        if table == slots or not _entry(clean, part.opening + 1, hit.start('statement')):
            continue
        if not re.search(rf'\bextern\s+unsigned\s+char\s+{re.escape(table)}\s*\[\s*\]\s*;', _blank(context)):
            continue
        if not re.search(rf'\bextern\s+char\s+{re.escape(slots)}\s*\[\s*\]\s*;', _blank(context)):
            continue
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+)(?:{re.escape(table)}|{re.escape(slots)})\s*(?:[;=,\[)]|$)')
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(table)}|{re.escape(slots)})\s*(?:[;=,\[])'
        if re.search(shadow, clean[signature:part.end]) or re.search(multi, clean[signature:part.end]):
            continue
        indent = re.match(r'[ \t]*', source[hit.start():hit.start('statement')])[0]
        read = source[hit.start('read'):hit.end('read')]
        sites.append(((hit['dest'], table), [(hit.start('statement'), hit.start('statement'), f'{local} = {read};\n{indent}'),
                                    (hit.start('read'), hit.end('read'), local)]))
        if len(sites) >= LIMIT:
            break
    decl_at = clean.find('\n', part.opening) + 1
    if not sites or not decl_at:
        return []
    def declaration(table):
        # Preserve the original operand's promoted type even if preprocessing
        # selects another compatible declaration of the external array.
        return (decl_at, decl_at, f'    __typeof__(*{table} + 0) {local};\n')

    result = [(FAMILY, edit(source, [declaration(table), *site])) for (_, table), site in sites]
    for key in dict.fromkeys(key for key, _ in sites):
        group = [site for target, site in sites if target == key]
        if len(group) > 1:
            result.append((FAMILY, edit(source, [declaration(key[1]), *(change for site in group for change in site)])))
    for table in dict.fromkeys(key[1] for key, _ in sites):
        group = [site for key, site in sites if key[1] == table]
        if len(group) > 1:
            result.append((FAMILY, edit(source, [declaration(table), *(change for site in group for change in site)])))
    return list(dict.fromkeys(result))


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
