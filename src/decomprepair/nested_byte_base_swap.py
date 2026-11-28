"""Swap two equivalent byte-table address spellings in nested reads.

A KMC O1 state handler holds a byte-table base in a stable local but uses the
symbol for the outer lookup and the local for the inner lookup. Swapping the
spellings preserved both reads and improved the linked diagnostic from 4515
to 4015, matching which lookup uses the materialized base. The judge decides.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'nested_byte_base_swap'
LIMIT = 6


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'\b(?:class|namespace|template|operator)\b|::', context):
        return []  # C++ overloads can make these apparent scalar operations observable
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|volatile|_Atomic|setjmp|longjmp|_Generic|typeof|__typeof__)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or {'s8', 'u8', name} & macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    if integer_abi.scalar('u8', _blank(context), 'mips') != (8, False):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    pattern = (rf'\b{IDENT}\s*\+\s*\(\s*{IDENT}\s*\+\s*(?P<symbol>{IDENT})\s*\)\s*\+\s*'
               rf'\*\s*\(\s*s8\s*\*\s*\)\s*\(\s*(?P<base>{IDENT})\s*\+\s*{IDENT}\s*\)')
    result = []
    for match in re.compile(pattern).finditer(clean, part.opening + 1, part.end):
        base, symbol = match['base'], match['symbol']
        if base == symbol or {base, symbol} & macros:
            continue
        if not re.search(rf'\bextern\s+char\s+{re.escape(symbol)}\s*\[\s*\]\s*;', _blank(context)):
            continue
        declarations = list(re.finditer(rf'(?m)^[ \t]*u8\s*\*\s*(?P<base>{re.escape(base)})\s*;[ \t]*$', clean[part.opening + 1:part.end]))
        if len(declarations) != 1:
            continue
        decl_at = part.opening + 1 + declarations[0].start('base')
        if any(part.opening < a < decl_at < b for a, b in pairs.items()):
            continue
        # No parameter, nested local, multi-declarator or macro can hide either name.
        signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
        if not signatures:
            continue
        signature = signatures[-1].start()
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(base)}|{re.escape(symbol)})\s*(?:[;=,\[)]|$)')
        if any(signature + m.start('name') != decl_at for m in re.finditer(shadow, clean[signature:part.end])):
            continue
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(base)}|{re.escape(symbol)})\s*(?:[;=,\[])'
        if re.search(multi, clean[signature:part.end]) or re.search(rf'\b(?:{re.escape(base)}|{re.escape(symbol)})\b', directives):
            continue
        if re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(base)}\b', body):
            continue
        writes = list(re.finditer(rf'(?<![\w.>]){re.escape(base)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(base)}\b', body))
        assignment = list(re.finditer(rf'(?m)^[ \t]*{re.escape(base)}\s*=\s*{re.escape(symbol)}\s*;\s*\n[ \t]*(?P<label>{IDENT})\s*:\s*\{{', body))
        if len(writes) != 1 or len(assignment) != 1:
            continue
        a = assignment[0]
        if not a.start() <= writes[0].start() < a.end():
            continue
        opening = part.opening + 1 + a.end() - 1
        end = close(clean, opening, '{', '}')
        label = a['label']
        if end and re.search(r'(?<![\w?:])'+IDENT+r'\s*:(?!:)', clean[opening + 1:end - 1]):
            continue  # no entry can jump past the base assignment
        if not end or not opening < match.start() < match.end() < end:
            continue
        jumps = list(re.finditer(rf'\bgoto\s+{re.escape(label)}\s*;', body))
        if (len(jumps) != 1 or part.opening + 1 + jumps[0].start() < end
                or len(re.findall(rf'\b{re.escape(label)}\s*:(?!:)', body)) != 1
                or re.search(rf'&&\s*{re.escape(label)}\b', body)):
            continue
        result.append((FAMILY, edit(source, [(match.start('symbol'), match.end('symbol'), base),
                                             (match.start('base'), match.end('base'), symbol)])))
        if len(result) >= LIMIT:
            return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
