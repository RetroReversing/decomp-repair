"""Stage a byte-row address used inside a nested call.

A KMC O1 state handler computes a table row inside a nested call. Naming the
real row address immediately before the call improved a linked diagnostic
from 3480 to 3260. A following row-plus-column stage improved a later
diagnostic from 1400 to 1160. Only pure call arguments qualify; the judge decides.
"""
import re

from .arm_block_support import brace_pairs
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'nested_row_address_stage'
LIMIT = 6


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
            or re.search(r'\b(?:asm|__asm__|_Atomic|setjmp|longjmp)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or {'u8', name} & macros:
        return []
    row = next((candidate for candidate in ('__repair_row_address', '__repair_row_address2')
                if candidate not in macros and not re.search(rf'\b{candidate}\b', clean)), None)
    if not row:
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if pairs is None or not signatures:
        return []
    signature = signatures[-1].start()
    row_pattern = re.compile(rf'(?P<column>{IDENT})\s*\+\s*\(\s*(?P<offset>{IDENT})\s*\+\s*(?P<base>{IDENT})\s*\)')
    column_pattern = re.compile(rf'(?P<offset>{IDENT})\s*\+\s*\(\s*(?P<base>{IDENT})\s*\)')
    line_pattern = re.compile(rf'(?m)^[ \t]*(?P<statement>{IDENT}\s*=(?!=)[^;{{}}\n]*;)')
    result = []
    for line in line_pattern.finditer(clean, part.opening + 1, part.end):
        start, end = line.start('statement'), line.end('statement')
        statement = clean[start:end]
        if clean[part.opening + 1:start].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        if (re.search(r'\b(?:sizeof|_Generic|typeof|__typeof__|__alignof__|_Alignof)\b', statement)
                or re.search(r'\+\+|--|\?|&&|\|\||(?<![=!<>])=(?!=)', statement[statement.index('=') + 1:])
                or re.search(r'\(\s*\*[^()]*\)\s*\(|\]\s*\(|(?:\(\s*\*\s*){2,}\(*\s*'+IDENT+r'\s*\)+\s*\(', statement)):
            continue
        calls = list(re.finditer(rf'\b{IDENT}\s*\(', statement))
        if len(calls) != 2:
            continue
        outer = close(statement, calls[0].end() - 1)
        inner = close(statement, calls[1].end() - 1)
        if not outer or not inner or not calls[0].end() <= calls[1].start() < inner <= outer:
            continue
        matches = [(m, False) for m in row_pattern.finditer(statement, calls[1].end(), inner)]
        matches += [(m, True) for m in column_pattern.finditer(statement, calls[1].end(), inner)]
        for match, whole in matches:
            base, offset = match['base'], match['offset']
            # Its exact byte pointer type matters when the row is added to a column.
            pointer = list(re.finditer(rf'(?m)^[ \t]*u8\s*\*\s*(?P<name>{re.escape(base)})\s*;', body))
            index = list(re.finditer(rf'(?m)^[ \t]*s32\s+(?P<name>{re.escape(offset)})\s*;', body))
            if len(pointer) != 1 or len(index) != 1 or base == offset:
                continue
            declarations = {base: part.opening + 1 + pointer[0].start('name'),
                            offset: part.opening + 1 + index[0].start('name')}
            if any(part.opening < a < at < b for at in declarations.values() for a, b in pairs.items()):
                continue
            shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                      rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(base)}|{re.escape(offset)})\s*(?:[;=,\[)]|$)')
            if any(signature + m.start('name') != declarations[m['name']]
                   for m in re.finditer(shadow, clean[signature:part.end])):
                continue
            multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(base)}|{re.escape(offset)})\s*(?:[;=,\[])'
            if re.search(multi, clean[signature:part.end]):
                continue
            decl_at = clean.find('\n', part.opening) + 1
            if not decl_at:
                continue
            indent = re.match(r'[ \t]*', source[line.start():start])[0]
            expression_start = start + (match.start() if whole else match.start('offset'))
            expression_end = start + (match.end() if whole else match.end('base'))
            result.append((FAMILY, edit(source, [(decl_at, decl_at, f'    u8 *{row};\n'),
                                                (start, start, f'{row} = {base} + {offset};\n{indent}'),
                                                (expression_start, expression_end, row)])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
