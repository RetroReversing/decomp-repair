"""Fold a bounded masked-index stride whose first product was staged.

A KMC O1 state handler expanded 100 times a masked halfword as 2, then add,
8, add, and 4 in two branches. Inlining the first products gave the same
bounded arithmetic and improved a linked diagnostic from 3245 to 2210. The
judge decides each individual and combined child.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'masked_stride_fold'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|setjmp|longjmp|__builtin_\w*)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or {'s32', name} & macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    if integer_abi.scalar('s32', _blank(context), 'mips') != (32, True):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if pairs is None or not signatures:
        return []
    signature = signatures[-1].start()
    params = set(re.findall(rf'\b(?:s32|int)\s+({IDENT})(?=\s*[,)]\s*)', clean[signature:part.opening]))
    assignment = re.compile(rf'(?m)^[ \t]*(?P<temp>{IDENT})\s*=\s*\(\s*(?P<arg>{IDENT})\s*&\s*0[xX][fF]{{4}}\s*\)\s*\*\s*2\s*;')
    sites = []
    for hit in assignment.finditer(clean, part.opening + 1, part.end):
        temp, arg = hit['temp'], hit['arg']
        if arg not in params or arg == temp:
            continue
        if re.search(rf'(?<![\w.>]){re.escape(arg)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(arg)}\b|(?<!&)\&(?!&)\s*\(*\s*{re.escape(arg)}\b', body):
            continue
        if re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(temp)}\b', body):
            continue
        declarations = list(re.finditer(rf'(?m)^[ \t]*s32\s+(?P<name>{re.escape(temp)})\s*;[ \t]*$', body))
        if len(declarations) != 1:
            continue
        decl_at = part.opening + 1 + declarations[0].start('name')
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(temp)}|{re.escape(arg)})\s*(?:[;=,\[)]|$)')
        shadows = list(re.finditer(shadow, clean[signature:part.end]))
        if len(shadows) != 2 or not any(signature + m.start('name') == decl_at for m in shadows):
            continue
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(temp)}|{re.escape(arg)})\s*(?:[;=,\[])'
        if re.search(multi, clean[signature:part.end]):
            continue
        masked = rf'\(\s*{re.escape(arg)}\s*&\s*0[xX][fF]{{4}}\s*\)'
        expanded = re.compile(rf'\(\s*\(\s*\(\s*\(\s*{re.escape(temp)}\s*\+\s*{masked}\s*\)\s*\*\s*8\s*\)\s*\+\s*{masked}\s*\)\s*\*\s*4\s*\)')
        uses = list(expanded.finditer(clean, hit.end(), part.end))
        if len(uses) != 1:
            continue
        use = uses[0]
        occurrences = list(re.finditer(rf'(?<![\w.>]){re.escape(temp)}\b', body))
        expected = {decl_at, hit.start('temp'), use.start() + use[0].find(temp)}
        if {part.opening + 1 + m.start() for m in occurrences} != expected:
            continue
        enclosing = [(a, b) for a, b in pairs.items() if a < decl_at < b]
        if not enclosing:
            continue
        a, b = max(enclosing)
        if not a < hit.start() < use.end() < b:
            continue
        decl_start = part.opening + 1 + declarations[0].start()
        decl_end = part.opening + 1 + declarations[0].end()
        sites.append([(decl_start, decl_end, ''), (hit.start('temp'), hit.end(), '(void) 0;'),
                      (use.start(), use.end(), f'(({arg} & 0xFFFF) * 100)')])
        if len(sites) >= LIMIT:
            break
    result = [(FAMILY, edit(source, site)) for site in sites]
    if len(sites) > 1:
        result.append((FAMILY, edit(source, [change for site in sites for change in site])))
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
