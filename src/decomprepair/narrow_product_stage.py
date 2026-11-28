"""Stage a narrow local's constant product after the local is loaded.

For an N64 state handler, staging a byte index times 0x178 before other
index calculations improved a KMC O1 diagnostic from 6850 to 6325. The
product remains a real call argument, and each child stages one product.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_product_stage'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b__LINE__\b', context):
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
    if macros.intersection(re.findall(IDENT, body)) or {'int', name, '__repair_product'} & macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []  # nested functions can access an outer local
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    # Function-local declaration of a genuinely unsigned byte, without shadows.
    declarations = re.compile(rf'(?m)^[ \t]*(?P<type>u8|unsigned\s+char)\s+(?P<var>{IDENT})\s*;[ \t]*$')
    result = []
    for decl in declarations.finditer(clean, part.opening + 1, part.end):
        var = decl['var']
        if any(part.opening < a < decl.start() < b for a, b in pairs.items()):
            continue
        if integer_abi.scalar(decl['type'], _blank(context), 'mips') != (8, False):
            continue
        shadow = rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}\s*(?:\*\s*|\s+)(?P<name>{re.escape(var)})\s*(?:[;=,\[)]|$)'
        if any(part.opening + m.start('name') != decl.start('var') for m in re.finditer(shadow, clean[part.opening:part.end])):
            continue
        if re.search(rf'&\s*\(*\s*{re.escape(var)}\b', body):
            continue
        writes = list(re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(var)}\b', body))
        if len(writes) != 1:
            continue
        assignment = re.compile(rf'(?m)^[ \t]*{re.escape(var)}\s*=(?!=)[^;{{}}]*;')
        assignments = list(assignment.finditer(body))
        if len(assignments) != 1 or assignments[0].start() > writes[0].start():
            continue
        assignment_start = part.opening + 1 + assignments[0].start()
        if clean[part.opening + 1:assignment_start].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue  # an unbraced control may govern the assignment
        anchor = part.opening + 1 + assignments[0].end()
        # Consecutive scalar assignments only: no jump, label, call, or change
        # to the index can intervene between the load and the product's use.
        run = re.match(rf'(?:\s*{IDENT}\s*=(?!=)\s*[^;{{}}()]*;)+', clean[anchor:part.end])
        if not run:
            continue
        call_start = anchor + run.end()
        call = re.match(rf'\s*{IDENT}\s*=(?!=)[^;{{}}]*\([^;{{}}]*;', clean[call_start:part.end])
        if not call:
            continue
        product = re.compile(rf'\(\s*{re.escape(var)}\s*\*\s*(?P<factor>0[xX][0-9a-fA-F]+|[0-9]+)\s*\)')
        for hit in product.finditer(clean, call_start, call_start + call.end()):
            factor = int(hit['factor'], 16 if hit['factor'].lower().startswith('0x') else 10)
            if not 1 < factor <= 8388607:
                continue
            local = '__repair_product'
            if re.search(rf'\b{local}\b', clean):
                continue
            line = clean.rfind('\n', 0, part.opening + 1) + 1
            decl_at = clean.find('\n', part.opening) + 1
            if not decl_at or line > decl_at:
                continue
            indent = re.match(r'[ \t]*', source[part.opening + 1 + assignments[0].start():])[0]
            result.append((FAMILY, edit(source, [(decl_at, decl_at, '    int '+local+';\n'),
                (anchor, anchor, '\n'+indent+local+' = '+var+' * '+hit['factor']+';'),
                (hit.start(), hit.end(), local)])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
