"""Stage the right byte read in a comparison of two indexed byte reads.

A KMC O1 state handler loads the right operand before the left; staging that
real byte read improved a linked diagnostic from 4015 to 3605. Both operands
are side-effect-free reads and the judge decides each child.
"""
import re

from . import integer_abi
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_compare_stage'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'\b(?:class|namespace|template|operator)\b|::', context):
        return []  # C++ overloads can make these apparent scalar operations observable
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|__LINE__)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|_Atomic|__LINE__)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or {'if', 'u8', name, '__repair_compare_byte'} & macros:
        return []
    if integer_abi.scalar('u8', _blank(context), 'mips') != (8, False):
        return []
    if re.search(r'\b__repair_compare_byte\b', clean):
        return []
    operand = rf'\(\s*u8\s*\)\s*\*\s*\(\s*{IDENT}\s*\+\s*{IDENT}\s*\)'
    pattern = rf'\bif\s*\(\s*(?P<left>{operand})\s*(?:<|>|<=|>=|==|!=)\s*(?P<right>{operand})\s*\)'
    result = []
    for match in re.compile(pattern).finditer(clean, part.opening + 1, part.end):
        if not re.match(r'\s*\{', clean[match.end():part.end]):
            continue
        if clean[part.opening + 1:match.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue  # an unbraced control or label may govern the if
        decl_at = clean.find('\n', part.opening) + 1
        if not decl_at:
            continue
        start = match.start()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        local = '__repair_compare_byte'
        right = source[match.start('right'):match.end('right')]
        result.append((FAMILY, edit(source, [(decl_at, decl_at, f'    u8 {local};\n'),
                                            (start, start, f'{local} = {right};\n{indent}'),
                                            (match.start('right'), match.end('right'), local)])))
        if len(result) >= LIMIT:
            return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
