"""Outline an early-return switch case at a void function's tail.

A KMC -O1 state handler put one returning arm after the main body. Moving that
arm there with a goto reduced its local linked score from 9930 to 7215. Only
cases whose names are visible at both sites are offered; a return before the
new label preserves ordinary fallthrough out of the function.
"""
import re

from .arm_block_support import brace_pairs, statements
from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .switch_case_tail_goto import _match, _segments

FAMILY = 'return_case_tail'
LIMIT = 4
TYPE = r'(?:[su](?:8|16|32|64)|int|short|long|char|unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int))'
KEYWORDS = {'if', 'else', 'return', 'sizeof', 'u8', 's8', 'u16', 's16', 'u32', 's32', 'u64', 's64',
            'int', 'short', 'long', 'char', 'unsigned', 'signed', 'void'}


def variants(source, name, header='', flags=None):
    if any(flag.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for flag in flags or ()):
        return []
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    clean = part.clean
    signature = clean[span[0]:part.opening]
    if not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', signature):
        return []
    if (re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', source + '\n' + header)
            or re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', clean[part.opening:part.end])
            or re.search(r'\b(?:typedef|struct|union|enum|__attribute__|asm|__asm__)\b', clean[part.opening:part.end])
            or re.search(r'\(\s*\*+\s*'+IDENT+r'\s*\)', clean[part.opening:part.end])):
        return []
    # Multiple declarators can introduce a shadow after the first name, which
    # the deliberately small declaration reader below cannot prove in scope.
    if re.search(r'(?:^|[;{}])\s*(?:(?:const|volatile|static|unsigned|signed|long|short)\s+)*'+IDENT
                 + r'\s*(?:\*\s*|\s+)'+IDENT+r'\s*(?:\[[^\]]*\])?[^;{}]*,[^;{}]*;',
                 clean[part.opening + 1:part.end]):
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{',
                 clean[part.opening + 1:part.end]):
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', source + '\n' + header))
    if macros & (KEYWORDS | {name}):
        return []
    braces = brace_pairs(clean, part.opening, part.end)
    if braces is None or part.opening not in braces:
        return []
    function_close = braces[part.opening]
    globals_ = set(re.findall(rf'\bextern\s+(?:(?:const|volatile)\s+)*{TYPE}\s*\**\s*({IDENT})\s*(?:\[|;)',
                              _blank(source[:span[0]] + '\n' + header)))
    params = set(re.findall(rf'\b{TYPE}\s*\**\s*({IDENT})\s*(?=,|\))', signature))
    local_pattern = re.compile(rf'(?m)^[ \t]*{TYPE}\s*\**\s*(?P<name>{IDENT})\s*;')
    locals_ = list(local_pattern.finditer(clean, part.opening + 1, part.end))
    result = []
    for found in re.finditer(r'\bswitch\s*\(', clean[part.opening + 1:part.end]):
        head = part.opening + 1 + found.start()
        condition_open = clean.find('(', head, part.end)
        condition_end = close(clean, condition_open) if condition_open >= 0 else None
        brace = re.match(r'\s*\{', clean[condition_end:part.end]) if condition_end else None
        opening = condition_end + brace.end() - 1 if brace else -1
        closing = _match(clean, opening) if opening >= 0 else None
        if closing is None or closing >= part.end:
            continue
        top_locals = {d['name'] for d in locals_ if d.start() < head
                      and not any(part.opening < a < d.start() < b for a, b in braces.items())}
        for start, end in _segments(clean, opening + 1, closing):
            text = clean[start:end]
            parts = statements(clean, start, end)
            if (not parts or not re.fullmatch(r'return\s*;', clean[parts[-1][0]:parts[-1][1]].strip())
                    or clean[parts[-1][1]:end].strip()):
                continue
            if re.search(r'\b(?:goto|break|continue|case|default|typedef|struct|union|enum|volatile)\b|(?<![\w?:])'+IDENT+r'\s*:(?!:)', text):
                continue
            if re.search(r'->|\.', text):
                continue  # a record name can be shadowed by a different type
            declaration = (rf'(?:^|[;{{}}])\s*(?:(?:const|volatile|static|unsigned|signed|long|short)\s+)*{IDENT}'
                           rf'\s*(?:\*\s*|\s+){IDENT}\s*(?:[;=,\[])')
            if re.search(declaration, text):
                continue
            # Calls and declarations need full scope and side-effect analysis.
            if re.search(rf'\b(?!(?:if|sizeof)\b){IDENT}\s*\(', text):
                continue
            ids = set(re.findall(r'(?<![\w.>])'+IDENT+r'\b', text))
            if macros & ids or not ids <= (KEYWORDS | globals_ | params | top_locals):
                continue
            # A declaration that would shadow an accessed name at either site
            # makes the same spelling refer to a different object after moving.
            shadow = re.compile(rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*(?P<type>{IDENT})'
                                rf'\s*(?:\*\s*|\s+)(?P<name>{IDENT})\s*(?:[;=,\[)]|$)')
            unsafe = False
            for decl in shadow.finditer(clean, part.opening + 1, part.end):
                if decl['type'] in {'if', 'else', 'return', 'goto', 'break', 'continue', 'case'}:
                    continue
                nested = any(part.opening < a < decl.start() < b for a, b in braces.items())
                # A new label must not jump into a later VLA's scope, even if
                # the outlined arm never mentions that declaration.
                if decl.start() > head and not nested:
                    unsafe = True
                    break
                if decl['name'] not in ids:
                    continue
                if any(part.opening < a < decl.start() < b and a < start < b for a, b in braces.items()):
                    unsafe = True
                    break
            if unsafe:
                continue
            label = '__repair_return_case'
            while re.search(rf'\b{re.escape(label)}\b', clean):
                label += '_'
            block = source[start:end].strip()
            tail = f'\n    return;\n{label}:\n    {block}\n'
            spacing = re.search(r'\n[ \t]*$', source[start:end])
            child = edit(source, [(start, end, f' goto {label};' + (spacing[0] if spacing else '\n')),
                                  (function_close, function_close, tail)])
            result.append((FAMILY, child))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'), 'archs': ('mips',)}
