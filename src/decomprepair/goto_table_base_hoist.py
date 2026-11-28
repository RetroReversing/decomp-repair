"""Hoist a stable table-address copy from a one-entry backward-goto loop.

In a KMC -O1 state handler, moving `base = table` before a labeled loop
restored the target's saved-register and stack layout and improved the local
linked score from 10566 to 9930, after correcting a post-call reload.
The symbol is an array, so taking its address has no side effects; the local
cannot escape, change, or be read before its original assignment.
"""
import re

from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'goto_table_base_hoist'
LIMIT = 4


def variants(source, name, header='', flags=None):
    if any(flag.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for flag in flags or ()):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', source + '\n' + header):
        return []
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|volatile|_Atomic)\b', body)):
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []  # nested functions can access an outer local without its address
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', source + '\n' + header))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    used_macros = macros.intersection(re.findall(IDENT, body))
    braces = brace_pairs(clean, part.opening, part.end)
    if braces is None:
        return []
    result = []
    labels = re.compile(rf'(?m)^[ \t]*(?P<label>{IDENT})\s*:\s*\{{')
    for label in labels.finditer(clean, part.opening + 1, part.end):
        label_name = label['label']
        if label_name in ('case', 'default') or label_name in macros:
            continue
        opening = label.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        tail = re.match(r'\s*if\s*\(', clean[end:part.end])
        cond_open = end + tail.end() - 1 if tail else -1
        cond_end = close(clean, cond_open) if cond_open >= 0 else None
        jump = re.match(rf'\s*goto\s+{re.escape(label_name)}\s*;', clean[cond_end:part.end]) if cond_end else None
        if not jump or re.match(r'\s*else\b', clean[cond_end + jump.end():part.end]):
            continue
        if (len(re.findall(rf'\bgoto\s+{re.escape(label_name)}\s*;', body)) != 1
                or len(re.findall(rf'\b{re.escape(label_name)}\s*:(?!:)', body)) != 1
                or re.search(rf'&&\s*{re.escape(label_name)}\b', body)
                or re.search(r'(?<![\w?:])'+IDENT+r'\s*:(?!:)', clean[opening + 1:end - 1])):
            continue
        for assignment in re.finditer(rf'(?m)^[ \t]*(?P<base>{IDENT})\s*=\s*(?P<symbol>{IDENT})\s*;[ \t]*\n?', clean[opening + 1:end - 1]):
            start = opening + 1 + assignment.start()
            stop = opening + 1 + assignment.end()
            base, symbol = assignment['base'], assignment['symbol']
            if base == symbol or {base, symbol, name} & macros:
                continue
            declaration = list(re.finditer(rf'(?m)^[ \t]*(?:char|s8|u8|void)\s*\*\s*(?P<name>{re.escape(base)})\s*;', body))
            if len(declaration) != 1 or any(part.opening < a < part.opening + 1 + declaration[0].start() < b for a, b in braces.items()):
                continue
            if not re.search(rf'\bextern\s+(?:char|s8|u8|unsigned\s+char|signed\s+char)\s+{re.escape(symbol)}\s*\[\s*\]\s*;', _blank(source + '\n' + header)):
                continue
            # No different-typed shadow of either spelling in the function.
            shadows = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                       rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(base)}|{re.escape(symbol)})\s*(?:[;=,\[)]|$)')
            decl_name = part.opening + 1 + declaration[0].start('name')
            signature = clean.rfind(name, 0, part.opening)
            if signature < 0 or any(signature + m.start('name') != decl_name
                                    for m in re.finditer(shadows, clean[signature:part.end])):
                continue
            if re.search(rf'\b(?:{re.escape(base)}|{re.escape(symbol)})\b', directives):
                continue
            if any(re.search(rf'\b{re.escape(macro)}\s*\([^;{{}}]*\b{re.escape(base)}\b', body) for macro in used_macros):
                continue
            if re.search(rf'&\s*\(*\s*{re.escape(base)}\b', body):
                continue
            # The assignment is at the loop body's top level, with no earlier
            # read, exit, call or hidden macro that could observe the change.
            if any(opening < a < start < b < end for a, b in braces.items()):
                continue
            prefix = clean[opening + 1:start]
            if (re.search(rf'\b{re.escape(base)}\b|\b(?:if|for|while|switch|case|default|goto|return|break|continue|asm|__asm__|volatile)\b|(?<![\w?:]){IDENT}\s*:(?!:)', prefix)
                    or re.search(rf'\b{IDENT}\s*\(', prefix) or used_macros.intersection(re.findall(IDENT, prefix))):
                continue
            writes = list(re.finditer(rf'(?<![\w.>]){re.escape(base)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(base)}\b', body))
            if len(writes) != 1 or part.opening + 1 + writes[0].start() != start + assignment[0].find(base):
                continue
            # The local's declaration cannot be hidden inside a different scope.
            indent = re.match(r'[ \t]*', source[label.start():])[0]
            insertion = indent + source[start:stop].strip() + '\n'
            result.append((FAMILY, edit(source, [(label.start(), label.start(), insertion), (start, stop, '')])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'), 'archs': ('mips',)}
