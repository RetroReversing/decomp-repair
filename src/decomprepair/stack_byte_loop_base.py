"""Retain a stack-byte buffer base through a guarded in-place copy loop."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stack_byte_loop_base'
BYTE = r'(?:u8|unsigned\s+char)'
REG = r'\$\w+'
ZERO = r'(?:0x0|0)?'
OFFSET = r'(?:0x[0-9a-fA-F]+|[0-9]+)'

TARGET = re.compile(
    rf'(?m)^addiu (?P<base>{REG}), \$sp, (?P<offset>{OFFSET})\n'
    rf'beqz (?P<head>{REG}), \.L\w+\n'
    r'sb (?P=head), (?P=offset)\(\$sp\)\n'
    rf'[^\n]+\n(?P<loop>\.L\w+):\naddu (?P<old>{REG}), (?P=base), (?P<idx>{REG})\n'
    rf'lbu (?P<byte>{REG}), {ZERO}\((?P=old)\)\n'
    rf'addiu (?P<input>{REG}), (?P=input), (?:1|0x1)\n'
    r'addiu (?P=idx), (?P=idx), (?:1|0x1)\n'
    r'addiu (?P=byte), (?P=byte), -(?:1|0x1)\n'
    rf'sb (?P=byte), {ZERO}\((?P=old)\)\n'
    rf'lbu (?P<next>{REG}), {ZERO}\((?P=input)\)\n'
    rf'(?:move|addu|or) (?P<dst>{REG}), (?P=base)(?:, \$zero)?\n'
    r'addu (?P=dst), (?P=dst), (?P=idx)\n'
    rf'bnez (?P=next), (?P=loop)\nsb (?P=next), {ZERO}\((?P=dst)\)$'
)

SOURCE = re.compile(
    rf'(?P<array>{IDENT})\s*\[\s*0\s*\]\s*=\s*(?P<head>{IDENT})\s*;\s*'
    r'if\s*\(\s*(?P=head)\s*!=\s*0\s*\)\s*{\s*'
    rf'(?P<input>{IDENT})\s*=\s*{IDENT}\s*;\s*do\s*{{\s*'
    rf'(?P<address>{IDENT})\s*=\s*(?P<old>&\s*(?:\(\s*(?P=array)\s*\)|(?P=array))\s*'
    rf'\[\s*(?P<index>{IDENT})\s*\])\s*;\s*'
    rf'(?P<value>{IDENT})\s*=\s*\*\s*(?P=address)\s*;\s*'
    r'(?P=input)\s*\+=\s*1\s*;\s*(?P=index)\s*\+=\s*1\s*;\s*'
    r'\*\s*(?P=address)\s*=\s*(?P=value)\s*-\s*1\s*;\s*'
    rf'(?P<next>{IDENT})\s*=\s*\*\s*(?P=input)\s*;\s*'
    r'(?P<new>(?:\(\s*(?P=array)\s*\)|(?P=array))\s*\[\s*(?P=index)\s*\])\s*=\s*(?P=next)\s*;\s*'
    r'}\s*while\s*\(\s*(?P=next)\s*!=\s*0\s*\)\s*;\s*}'
)


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not (part := view(source, name)) or '$sp' not in asm:
        return []
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    lines = '\n'.join(' '.join(line.split()) for line in assembly.splitlines())
    if not TARGET.search(lines):
        return []
    for loop in SOURCE.finditer(part.clean, part.opening + 1, part.end):
        array = loop['array']
        if part.clean[part.opening:loop.start()].rstrip()[-1:] not in {';', '{', '}', ':'}:
            continue
        # The local declaration section precedes the first statement in this form.
        declarations = re.match(r'(?:\s*[^;{}=]+;)+', part.body)
        local_array = rf'\b(?P<type>{BYTE})\s+{array}\s*\[\s*[1-9][0-9]*\s*\]\s*;'
        if not declarations or not (decl := re.search(local_array, declarations[0])):
            continue
        pointer = '__repair_byte_buffer'
        used = set(re.findall(IDENT, part.clean + '\n' + header))
        while pointer in used:
            pointer += '_'
        indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, loop.start()) + 1:]).group()
        text = edit(source, [
            (part.opening + 1, part.opening + 1, f'\n    {decl["type"]} *{pointer};'),
            (loop.start(), loop.start(), f'{pointer} = {array};\n{indent}'),
            (*loop.span('old'), f'{pointer} + {loop["index"]}'),
            (*loop.span('new'), f'{pointer}[{loop["index"]}]'),
        ])
        return [(FAMILY, text)]
    return []
