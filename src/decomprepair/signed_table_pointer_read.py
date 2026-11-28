"""Use the target's byte signedness for a read through a stable table pointer.

A KMC -O1 state handler reads an indexed table byte through a `u8 *` local,
then uses it as a further offset. The target's sole table load is `lb`, so the
read is through `s8 *`: its local linked score improved from 10202 to 10007.
The full table symbol and a stable pointer assignment tie the load evidence to
the source; this proposes one read at a time for the exact judge.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .asm_symbol_read_width import _address_widths, _aliases
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'signed_table_pointer_read'
LIMIT = 6
DECL = re.compile(rf'(?m)^[ \t]*(?P<type>u8|s8)\s*\*\s*(?P<name>{IDENT})\s*;[ \t]*$')


def variants(source, name, asm='', header='', flags=None):
    if any(flag.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for flag in flags or ()):
        return []
    part = view(source, name)
    if not part:
        return []
    context = source + '\n' + header
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', directives):
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros & {'s8', 'u8', name}:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    braces = brace_pairs(clean, part.opening, part.end)
    if braces is None:
        return []
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|volatile|_Atomic|typeof|__typeof__|__alignof__|_Generic)\b', body)):
        return []
    direct = {}
    for op, symbol in re.findall(r'\b(lbu|lb|lhu|lh|lw)\s+\$\w+\s*,\s*%lo\(\s*('+IDENT+r')\s*\)', asm or ''):
        direct.setdefault(symbol, set()).add(op)
    result = []
    for symbol, wanted in sorted(_address_widths(asm).items()):
        if wanted not in ('s8', 'u8') or direct.get(symbol) != ({'lb'} if wanted == 's8' else {'lbu'}) or symbol in macros:
            continue
        if not re.search(rf'\bextern\s+(?:char|s8|u8|unsigned\s+char|signed\s+char)\s+{re.escape(symbol)}\s*\[\s*\]\s*;', clean):
            continue
        # A local or parameter with the symbol's name is not the global table.
        symbol_shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                         rf'\s*(?:\*\s*|\s+){re.escape(symbol)}\s*(?:[;=,\[)]|$)')
        if re.search(symbol_shadow, clean[clean.rfind(name, 0, part.opening):part.end]):
            continue
        for base in _aliases(clean[part.opening:part.end], symbol):
            declarations = [d for d in DECL.finditer(clean, part.opening + 1, part.end) if d['name'] == base]
            if len(declarations) != 1 or base in macros or re.search(rf'&\s*\(*\s*{re.escape(base)}\b', body):
                continue
            declared = declarations[0]['type']
            if declared == wanted or integer_abi.scalar(declared, _blank(context), 'mips') != (8, declared == 's8'):
                continue
            if integer_abi.scalar(wanted, _blank(context), 'mips') != (8, wanted == 's8'):
                continue
            if re.search(rf'\b(?:{re.escape(base)}|{re.escape(symbol)})\b', directives):
                continue
            used_macros = macros.intersection(re.findall(IDENT, body))
            if any(re.search(rf'\b{re.escape(macro)}\s*\([^;{{}}]*\b{re.escape(base)}\b', body)
                   for macro in used_macros):
                continue
            # Reject another declaration, including an inner shadow of a different type.
            shadow = rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}\s*(?:\*\s*|\s+)(?P<name>{re.escape(base)})\s*(?:[;=,\[)]|$)'
            if any(part.opening + 1 + m.start('name') != declarations[0].start('name')
                   for m in re.finditer(shadow, clean[part.opening + 1:part.end])):
                continue
            assignments = list(re.finditer(rf'(?<![\w.>]){re.escape(base)}\s*=\s*{re.escape(symbol)}\s*;',
                                           clean[part.opening + 1:part.end]))
            if len(assignments) != 1:
                continue
            assignment_start = part.opening + 1 + assignments[0].start()
            assignment_end = part.opening + 1 + assignments[0].end()
            prefix = clean[part.opening + 1:assignment_start].rstrip()
            if prefix and prefix[-1] not in ';{}':
                continue  # a conditional statement could skip the assignment
            read = re.compile(rf'\*\s*\(\s*{re.escape(base)}\s*\+\s*{IDENT}\s*\)')
            for hit in read.finditer(clean, part.opening + 1, part.end):
                if hit.start() < assignment_end or any(a < assignment_start < b < hit.start() for a, b in braces.items()):
                    continue
                if re.search(r'\b(?:goto|case|default)\b|(?<![\w?:])'+IDENT+r'\s*:(?!:)',
                             clean[assignment_end:hit.start()]):
                    continue
                before = clean[part.opening + 1:hit.start()].rstrip()
                after = clean[hit.end():]
                if (before.endswith((')', ']')) or re.search(r'(?:\+\+|--)\s*\(*\s*$', before)
                        or re.search(r'&\s*\(*\s*$', before)
                        or re.search(r'\bsizeof\s*\(*\s*$', before)
                        or (re.search(r'\w$', before) and not re.search(r'\breturn$', before))
                        or re.match(r'\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))', after)):
                    continue
                result.append((FAMILY, edit(source, [(hit.start() + 1, hit.start() + 1, f'({wanted} *)')])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'asm', 'header', 'flags'), 'archs': ('mips',)}
