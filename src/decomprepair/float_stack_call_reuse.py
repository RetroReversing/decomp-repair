"""Reuse the two float loads the target stores to its stack and passes to a call."""
import re

from .csource import _blank, find

FAMILY = 'float_stack_call_reuse'
ID = r'[A-Za-z_]\w*'
FLOAT = r'(?:float|f32)'
ARG0 = r'(?:\$fa0|\$f12)'
ARG1 = r'(?:\$fa1|\$f14)'
OFFSET = r'(?:0[xX][\da-fA-F]+|\d+)'
APPROX = re.compile(
    rf'(?m)^\s*lwc1\s+{ARG0},\s*(?:0x0|0)?\((\$\w+)\)\s*\n'
    rf'\s*swc1\s+{ARG0},\s*{OFFSET}\(\$sp\)\s*\n'
    rf'\s*lwc1\s+(\$\w+),\s*(?:4|0x4)\(\1\)\s*\n'
    rf'\s*swc1\s+\2,\s*{OFFSET}\(\$sp\)\s*\n'
    rf'\s*lwc1\s+{ARG1},\s*(?:8|0x8)\(\1\)\s*\n'
    rf'\s*jal\s+{ID}\s*\n\s*swc1\s+{ARG1},\s*{OFFSET}\(\$sp\)'
)
COPY = re.compile(
    rf'(?P<first>{ID})\s*=\s*(?P<helper>{ID})\(\s*(?P<base>{ID})\s*,\s*0\s*\)\s*;\s*'
    rf'(?P<middle>{ID})\s*=\s*(?P=helper)\(\s*(?P=base)\s*,\s*4\s*\)\s*;\s*'
    rf'(?P<last>{ID})\s*=\s*(?P<last_helper>(?P=helper))\(\s*(?P=base)\s*,\s*8\s*\)\s*;'
)


def _reads_float(clean, helper):
    declaration = re.search(
        rf'\bstatic\s+const\s+{FLOAT}\s+{helper}\(\s*const\s+{FLOAT}\s*\*\s*({ID})\s*,\s*int\s+({ID})\s*\)',
        clean,
    )
    if not declaration:
        return False
    base, offset = declaration.groups()
    return bool(re.match(
        rf'\s*{{\s*return\s+\*\(\s*\(\s*const\s+{FLOAT}\s*\*\s*\)\s*'
        rf'\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{base}\s*\)\s*\+\s*{offset}\s*\)\s*\)\s*;\s*}}',
        clean[declaration.end():],
    ))


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not APPROX.search(re.sub(r'/\*[^\n]*?\*/', '', asm)):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    for copy in COPY.finditer(clean, *span):
        first, middle, last = (copy[k] for k in ('first', 'middle', 'last'))
        base = copy['base']
        if len({first, middle, last}) != 3 or not _reads_float(clean, copy['helper']):
            continue
        declarations = [re.search(rf'\bvolatile\s+{FLOAT}\s+{var}\s*;', clean[span[0]:copy.start()])
                        for var in (first, middle, last)]
        if not all(declarations):
            continue
        opening = clean.find('{', *span)
        if not re.search(rf'\bconst\s+{FLOAT}\s*\*\s*{base}\b', clean[span[0]:opening]):
            continue
        # The duplicate reads must be the two arguments of a nested call in the next assignment.
        stmt_end = clean.find(';', copy.end(), span[1])
        if stmt_end < 0:
            continue
        call = re.search(
            rf'\b{ID}\(\s*{middle}\s*,\s*(?P<inner>{ID}\(\s*{base}\s*\[\s*0\s*\]\s*,'
            rf'\s*{base}\s*\[\s*2\s*\]\s*\))\s*\)',
            clean[copy.end():stmt_end],
        )
        if not call or re.search(rf'\b{ID}\s*\(', clean[copy.end():copy.end()+call.start()]):
            continue
        used = set(re.findall(ID, clean+'\n'+header))
        x, z, result = ('__repair_' + key for key in ('float_x', 'float_z', 'float_call'))
        while {x, z, result} & used:
            x += '_'
            z += '_'
            result += '_'
        inner_start, inner_end = (copy.end()+at for at in call.span('inner'))
        callee = call['inner'].split('(', 1)[0]
        indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, copy.start())+1:]).group()
        declaration_end = span[0]+max(match.end() for match in declarations)
        declaration_indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, declaration_end)+1:]).group()
        text = (source[:declaration_end] + f'\n{declaration_indent}float {x}, {z}, {result};'
                + source[declaration_end:copy.start('helper')] + f'{x} = '
                + source[copy.start('helper'):copy.start('last_helper')] + f'{z} = '
                + source[copy.start('last_helper'):copy.end()] + f'\n{indent}{result} = {callee}({x}, {z});'
                + source[copy.end():inner_start] + result + source[inner_end:])
        return [(FAMILY, text)]
    return []
