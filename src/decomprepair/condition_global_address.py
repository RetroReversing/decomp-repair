"""Stage the address of a scalar byte read repeatedly in one condition.

A KMC O1 state handler reloads the same byte twice around an intervening
store; the target keeps its address in a register. Naming that address in a
local improved the linked diagnostic from 5020 to 4515. The pointer does not
cache the value, so both original reads remain. The judge decides each child.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'condition_global_address'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|volatile|_Atomic|setjmp|longjmp)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or {'if', name, '__repair_byte_address'} & macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    if re.search(r'\b__repair_byte_address\b', clean):
        return []
    symbols = re.findall(rf'(?m)^\s*extern\s+(u8|unsigned\s+char)\s+({IDENT})\s*;', _blank(context))
    result = []
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if not signatures:
        return []
    signature = signatures[-1].start()
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening + 1:part.end]):
        start = part.opening + 1 + hit.start()
        opening = part.opening + hit.end()
        end = close(clean, opening)
        if not end or not re.match(r'\s*\{', clean[end:part.end]):
            continue
        if clean[part.opening + 1:start].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue  # another unbraced control or label could govern this if
        condition = clean[opening + 1:end - 1]
        if re.search(r'[{}#]', condition):
            continue
        for kind, symbol in symbols:
            if symbol in macros or re.search(rf'\b{re.escape(symbol)}\b', directives):
                continue
            shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                      rf'\s*(?:\*\s*|\s+){re.escape(symbol)}\s*(?:[;=,\[)]|$)')
            if re.search(shadow, clean[signature:part.end]):
                continue
            uses = list(re.finditer(rf'(?<![\w.>]){re.escape(symbol)}\b', condition))
            if len(uses) < 2:
                continue
            if re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(symbol)}\b|(?<![\w.>]){re.escape(symbol)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(symbol)}\b', condition):
                continue
            decl_at = clean.find('\n', part.opening) + 1
            if not decl_at:
                continue
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
            pointer = '__repair_byte_address'
            edits = [(decl_at, decl_at, f'    {kind} *{pointer};\n'),
                     (start, start, f'{pointer} = &{symbol};\n{indent}')]
            edits += [(opening + 1 + m.start(), opening + 1 + m.end(), f'(*{pointer})') for m in uses]
            result.append((FAMILY, edit(source, edits)))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
