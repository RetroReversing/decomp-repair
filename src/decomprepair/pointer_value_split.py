"""Split a stable pointer value before a later member store.

A voice pointer in an N64 audio handler had the target's stack spill but stayed in a saved register. Copying the
pointer immediately after its one initialization and using that copy in a later event-field store changed the
allocation: 686 -> 365 with GCC 2.7.2 KMC, -G0 -mips3 -mgp32 -mfp32 -O2. The copy and one-shot scope are compiler
scaffolding, not evidence that the original source used them. Every child still needs the ordinary byte judge.

Only a plain, unescaped pointer initialized once from a field address is eligible. Capture and store must be in the
same lexical block, with no jump into the interval, pointer update, or macro invocation that could change its value.
"""
import re

from .call_lifetime_repairs import block_path
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .local_read_fence import _pointers
from .local_weight_ladder import _declaration

FAMILY = 'pointer_value_split'
LIMIT = 48


def _declarations(part, name):
    found = []
    offset = part.opening + 1
    for line in part.clean[offset:part.end].splitlines(keepends=True):
        match = _declaration(line.rstrip('\r\n'))
        if match and match['name'] == name:
            found.append((offset + len(line.rstrip('\r\n')), match['indent']))
        offset += len(line)
    return found


def variants(source, name, header='', flags=()):
    # Unknown included or command-line macros could write the local without naming it at the call site.
    if re.search(r'(?m)^\s*#\s*include\b', source + '\n' + header) or any(
            (str(flag).startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '-std=c++', '-std=gnu++'))
             or str(flag) in ('c++', 'c++-header')) for flag in flags):
        return []
    # C++ references can mutate a local without an explicit `&local` at the call site.
    combined = source + '\n' + header
    if (re.search(r'\b(?:class|namespace|template|auto|operator|decltype|constexpr|new|delete|this|using)\b|extern\s*"C"', combined)
            or re.search(rf'(?<![\w.>]){IDENT}\s*\**\s*&\s*{IDENT}\b', _blank(combined))):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|asm|__asm|__asm__|setjmp|longjmp|__builtin_setjmp|__builtin_longjmp)\b', part.body):
        return []
    clean = part.clean
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', source + '\n' + header))
    # A macro used even before capture could save the address of the local for a later callback.
    if macros.intersection(re.findall(IDENT, part.body)):
        return []
    # Nested GNU C functions can capture and change a local without an explicit address expression.
    if re.search(rf'\b(?:void|char|short|int|long|float|double|s32|u32)\s+\**\s*{IDENT}\s*\([^;{{}}]*\)\s*\{{', part.body):
        return []
    result = []
    for local, declared in sorted(_pointers(source, name).items()):
        if local.startswith('__'):
            continue
        escaped = re.escape(local)
        alias = '__split_' + local
        if local in macros or alias in macros:
            continue
        if re.search(rf'\b{re.escape(alias)}\b', _blank(source + '\n' + header)):
            continue
        declarations = _declarations(part, local)
        # A grouped declaration can shadow the name but is not recognized by the single-declarator parser.
        groups = re.finditer(rf'(?<=[;{{}}])\s*(?:(?:struct|union|enum)\s+)?{IDENT}(?:\s+{IDENT})*\s+[^;{{}}]*,[^;{{}}]*;', '{' + part.body)
        if any(re.search(rf'(?<![\w.>]){escaped}\b', group[0]) for group in groups):
            continue
        if (len(declarations) != 1 or re.search(rf'&\s*(?:\(\s*)*{escaped}\b', part.body)
                or re.search(rf'\b(?:struct|union|enum)\s+{IDENT}\s*\*+\s*{escaped}\b', part.body)):
            continue
        # A single definition means every later read retains the captured value. Parenthesized writes and
        # increments are excluded too, including writes in other arms of the function.
        wrapped = rf'(?:\(\s*)*{escaped}\b(?:\s*\))*'
        writes = list(re.finditer(rf'(?<![\w.>]){wrapped}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', part.body))
        if len(writes) != 1 or re.search(rf'(?:\+\+|--)\s*{wrapped}|(?<![\w.>]){wrapped}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)', part.body):
            continue
        field = rf'&\s*{IDENT}(?:\s*(?:->|\.)\s*{IDENT})+'
        assignment = rf'{escaped}\s*=\s*{field}\s*;'
        scoped = re.search(rf'\bdo\s*\{{\s*{assignment}\s*\}}\s*while\s*\(\s*0\s*\)\s*;', clean[part.opening:part.end])
        plain = re.search(assignment, clean[part.opening:part.end]) if not scoped else None
        init = scoped or plain
        if not init:
            continue
        begin, capture = part.opening + init.start(), part.opening + init.end()
        # Do not add a statement to an unbraced conditional or loop body.
        if clean[part.opening:begin].rstrip()[-1:] not in ('{', '}', ';'):
            continue
        lhs = rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT})+'
        stores = re.finditer(rf'(?<![\w.>]){lhs}\s*=\s*(?P<read>{escaped})\s*;', clean[capture:part.end])
        for store in stores:
            read = capture + store.start('read')
            between = clean[capture:read]
            if block_path(part, begin) != block_path(part, capture + store.start()):
                continue
            if re.search(r'\bcase\b|\bdefault\s*:', between):
                continue
            declaration, indent = declarations[0]
            for depth in (0, 1, 2):
                copy = 'do { ' * depth + f'{alias} = {local};' + ' } while (0);' * depth
                result.append((FAMILY, edit(source, [(declaration, declaration, f'\n{indent}{declared}{alias};'),
                                                       (capture, capture, ' ' + copy),
                                                       (read, read + len(local), alias)])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'), 'archs': ('mips',)}
