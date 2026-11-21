"""Recover three untyped word-access shapes using the target's MIPS instructions."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips_returns import instructions
from .pattern_repairs import close

REG = r'\$[a-z][a-z0-9]*'
ZERO = r'(?:0x0|0)?'
SHIFT = r'(?:0x2|2)'
INDEX_SCALE = r'(?:0x4|4)'
LOOKUP = re.compile(
    rf'lw (?P<object>{REG}), (?P<object_offset>{NUMBER})\(\$a0\)\n'
    rf'lbu (?P<index>{REG}), {ZERO}\(\$a1\)\n'
    rf'lw (?P<table>{REG}), (?P<table_offset>{NUMBER})\((?P=object)\)\n'
    rf'sll (?P=index), (?P=index), {SHIFT}\n'
    r'addu (?P=index), (?P=index), (?P=table)\n'
    rf'lw (?P=index), {ZERO}\((?P=index)\)\n'
    r'addu (?P=object), (?P=object), (?P=index)\n'
    r'addiu \$v0, \$a1, (?:0x1|1)\njr \$ra\n'
    rf'sw (?P=object), (?P<store_offset>{NUMBER})\(\$a0\)',
)
COMPARISON = re.compile(
    rf'lbu (?P<first>{REG}), {ZERO}\(\$a0\)\n'
    rf'lui (?P<base>{REG}), %hi\((?P<symbol>{IDENT}) \+ (?P<offset>{NUMBER})\)\n'
    r'addiu (?P=base), (?P=base), %lo\((?P=symbol) \+ (?P=offset)\)\n'
    rf'lbu (?P<second>{REG}), {ZERO}\(\$a1\)\n'
    rf'sll (?P=first), (?P=first), {SHIFT}\n'
    r'addu (?P=first), (?P=first), (?P=base)\n'
    rf'sll (?P=second), (?P=second), {SHIFT}\n'
    r'addu (?P=second), (?P=second), (?P=base)\n'
    rf'lw (?P=first), {ZERO}\((?P=first)\)\n'
    rf'lw (?P=second), {ZERO}\((?P=second)\)\n'
    r'jr \$ra\nsltu \$v0, (?P=second), (?P=first)',
)
MAPPED_STORE = re.compile(
    rf'(?m)^lui (?P<base>{REG}), %hi\((?P<segment>D_A0000000)\)\n'
    rf'or (?P=base), (?P<address>{REG}), (?P=base)\n'
    rf'sw (?P<value>{REG}), %lo\((?P=segment)\)\((?P=base)\)$',
)


def variants(source, name, asm, header=''):
    """Supply one source candidate with a word width established by the target."""
    if not asm or '*(' not in source:
        return []
    if 'sll' in asm and 'lw' in asm:
        text = _assembly(asm)
        if lookup := LOOKUP.fullmatch(text):
            if candidate := _lookup(source, name, lookup):
                return [('initial_typed_index_word', candidate)]
        if comparison := COMPARISON.fullmatch(text):
            if candidate := _comparison(source, name, header, comparison):
                return [('initial_indexed_word_comparison', candidate)]
    if 'D_A0000000' in source and '%hi(D_A0000000)' in asm:
        if candidate := _store(source, name, header, _assembly(asm)):
            return [('initial_mapped_word_store', candidate)]
    return []


def _assembly(asm):
    return '\n'.join(' '.join(line.split()) for line in instructions(asm))


def _lookup(source, name, target):
    part = view(source, name)
    if not part or len({target['object'], target['index'], target['table'], '$a0', '$a1'}) != 5:
        return None
    c = re.search(
        rf'\b(?P<local>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P<owner>{IDENT}),\s*void\s*\*\s*\*,\s*'
        rf'(?P<object_offset>{NUMBER})\s*\);\s*'
        rf'M2C_FIELD\(\s*(?P=owner),\s*void\s*\*\s*\*,\s*(?P<store_offset>{NUMBER})\s*\)\s*=\s*'
        rf'\(void\s*\*\)\s*\(\s*(?P=local)\s*\+\s*\*(?P<address>\(\s*\(\s*\*\s*(?P<index>{IDENT})'
        rf'\s*\*\s*{INDEX_SCALE}\s*\)\s*\+\s*M2C_FIELD\(\s*(?P=local),\s*s32\s*\*,\s*'
        rf'(?P<table_offset>{NUMBER})\s*\)\s*\))\s*\);\s*return\s+(?P=index)\s*\+\s*1\s*;',
        part.body)
    fields = ('object_offset', 'store_offset', 'table_offset')
    if not c or any(integer(c[field]) != integer(target[field]) for field in fields):
        return None
    signature = part.clean[:part.opening]
    if not re.search(rf'\b{re.escape(name)}\s*\(\s*void\s*\*\s*{c["owner"]}\s*,\s*u8\s*\*\s*{c["index"]}\s*\)\s*$',
                     signature):
        return None
    return edit(source, [(part.opening + 1 + c.start('address'), part.opening + 1 + c.start('address'), '(s32 *)')])


def _comparison(source, name, header, target):
    entry, score = '__repair_entry', '__repair_score'
    part = view(source, name)
    if not part or any(re.search(rf'\b{local}\b', source + header) for local in (entry, score)):
        return None
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return None
    body = part.clean[part.opening + 1:end - 1]
    symbol = target['symbol']
    if len({target['first'], target['second'], target['base']}) != 3:
        return None
    decl = re.match(rf'\s*void\s*\*\s*(?P<base>{IDENT})\s*;', body)
    if not decl:
        return None
    base = decl['base']
    comparison = re.fullmatch(
        rf'\s*{base}\s*=\s*(?P<cast>\(char\s*\*\)\s*)?(?P<address>&{symbol})\s*\+\s*(?P<offset>{NUMBER})\s*;\s*'
        rf'(?P<result>return\s+\(u32\)\s*\*\(\(\*(?P<second>{IDENT})\s*\*\s*{INDEX_SCALE}\)\s*\+\s*{base}\)'
        rf'\s*<\s*\(u32\)\s*\*\(\(\*(?P<first>{IDENT})\s*\*\s*{INDEX_SCALE}\)\s*\+\s*{base}\);)\s*',
        body[decl.end():])
    if not comparison or integer(comparison['offset']) != integer(target['offset']):
        return None
    first, second = comparison['first'], comparison['second']
    if not re.search(rf'\b{re.escape(name)}\s*\(\s*u8\s*\*\s*{first}\s*,\s*u8\s*\*\s*{second}\s*\)\s*$',
                     part.clean[:part.opening]):
        return None
    start = part.opening + 1 + decl.end()
    result = (f'{entry} = {base} + (*{first} * 4);\n'
              f'    return *(u32 *)({base} + (*{second} * 4)) < ({score} = *(u32 *){entry});')
    declaration = f'\n    void *{entry};\n    u32 {score};'
    edits = [(start, start, declaration),
             (start + comparison.start('result'), start + comparison.end('result'), result)]
    if not comparison['cast']:
        address = start + comparison.start('address')
        edits.append((address, address, '(char *)'))
    return edit(source, edits)


def _store(source, name, header, target):
    sites = list(MAPPED_STORE.finditer(target))
    if len(sites) != 1 or re.search(r'\bD_A0000000\b', header):
        return None
    base, address, value = (sites[0][role] for role in ('base', 'address', 'value'))
    if len({base, address, value}) != 3:
        return None
    part = view(source, name)
    if not part or not re.search(r'(?m)^extern M2C_UNK D_A0000000\s*;', part.clean[:part.opening]):
        return None
    signature = re.search(rf'\b{re.escape(name)}\s*\(\s*[su]32\s+(?P<address>{IDENT})\s*,\s*'
                          rf'[su]32\s+(?P<value>{IDENT})\s*\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    statement = re.search(
        rf'(?m)^[ \t]*(?P<store>\*\(\s*{signature["address"]}\s*\|\s*\(s32\)\s*&D_A0000000\s*\))'
        rf'\s*=\s*{signature["value"]}\s*;', part.body)
    if not statement or part.body.count('D_A0000000') != 1:
        return None
    left = part.opening + 1
    return edit(source, [(left + statement.start('store'), left + statement.end('store'),
                         f'*(volatile u32 *)({signature["address"]} | 0xA0000000U)')])
