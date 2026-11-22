"""Recover two stores through a repeatedly loaded relocated pointer."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<ptr>{IDENT})\)\nlw \$v1, %lo\((?P=ptr)\)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<first>{IDENT})\)\nlw \$v0, %lo\((?P=first)\)\(\$v0\)\n'
    r'sw \$v0, 4\(\$v1\)\n'
    r'lui \$v1, %hi\((?P=ptr)\)\nlw \$v1, %lo\((?P=ptr)\)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<second>{IDENT})\)\nlw \$v0, %lo\((?P=second)\)\(\$v0\)\n'
    r'sw \$v0, \(\$v1\)\njr \$ra\naddiu \$v0, \$zero, 1'
)
_SOURCE = _shape('''
    M2C_FIELD(M2C_FIELD(&@owner, void **, @pointer), s32 *, 4) = (s32) M2C_FIELD(&@data, s32 *, @first);
    M2C_FIELD(M2C_FIELD(&@owner, void **, @pointer), s32 *, 0) = (s32) M2C_FIELD(&@data, s32 *, @second);
    return 1;
''', numbers=('pointer', 'first', 'second'))


def _word_address_writeback(source, name, header, rows, resolve):
    """Keep a relocated word store's address sum in the loaded base local."""
    destinations = []
    for add, high, store in zip(rows, rows[1:], rows[2:]):
        target = re.fullmatch(r'addu (\$\w+), \1, (\$\w+)', add[1])
        symbol = re.fullmatch(rf'lui \$at, %hi\(({IDENT})\)', high[1])
        if not target or not symbol or target[1] == target[2] or high[1] != high[2]:
            continue
        base, stride = target.groups()
        if add[2] != f'addu {stride}, {base}, {stride}':
            continue
        low = f'%lo({symbol[1]})($at)'
        if store[1] != f'sw {base}, {low}' or store[2] != f'sw {stride}, {low}':
            continue
        destinations.append(symbol[1])
    if len(destinations) != 1 or not (part := view(source, name)):
        return None
    symbol = destinations[0]
    target_address = resolve(symbol) if resolve else None
    context = header + '\n' + part.clean[:part.opening]
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<global>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*'
        rf'(?P<stride>[A-Za-z_0-9()<>+* \t]+?)\s*;'
    )
    choices = []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        dest, base, stride = hit['global'], hit['base'], hit['stride']
        if dest != symbol and (target_address is None or resolve(dest) != target_address):
            continue
        if not re.search(rf'\bextern\s+(?:s32|u32)\s+{dest}\s*;', context):
            continue
        if not re.fullmatch(rf'\(*\s*\(*\s*{IDENT}\s*\+\s*1\s*\)\s*<<\s*\d+\s*\)*'
                            r'(?:\s*<<\s*\d+\s*\)*)?', stride.strip()):
            continue
        refs = re.compile(rf'(?<![\w.>]){base}\b')
        prefix = part.clean[part.opening:hit.start()]
        suffix = part.clean[hit.end():part.end]
        if (len(refs.findall(prefix)) != 2 or re.search(rf'&\s*\(*\s*{base}\b', part.body)
                or not re.search(rf'(?m)^[ \t]*u32\s+{base}\s*;', prefix)
                or not re.search(rf'\b{base}\s*=\s*\(*\s*\*\s*\(+\s*u32\s*\*\s*\)', prefix)):
            continue
        later = refs.search(suffix)
        if later:
            overwrite = re.match(r'\s*=(?!=)([^;]+);', suffix[later.end():])
            if (not overwrite or refs.search(overwrite[1])
                    or not re.fullmatch(r'(?:[^;{}#]*;)*\s*', suffix[:later.start()])
                    or re.search(r'\b(?:if|else|goto|return|switch|for|while|do)\b', suffix[:later.start()])):
                continue
        if re.search(rf'(?m)^[ \t]*#\s*define\s+(?:{base}|{dest})\b', context):
            continue
        if re.search(r'/[*/]', source[hit.start():hit.end()]):
            continue
        choices.append((hit.start(), hit.end(),
                        f'{hit["indent"]}{base} += {stride}; {dest} = {base};'))
    return edit(source, choices) if len(choices) == 1 else None


def variants(source, name, header, rows, resolve=None):
    if candidate := _word_address_writeback(source, name, header, rows, resolve):
        return [('measured_word_address_writeback', candidate)]
    if not resolve or len(rows) != 12:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not observed or (f'lui $v0, %hi({observed["second"]})', '') not in changes:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    sig = re.search(rf'\bs32 {re.escape(name)}\(void\)\s*$', part.clean[:part.opening])
    if not draft or not sig or re.search(r'\bvolatile\b', part.body):
        return []
    context = part.clean + '\n' + _blank(header)
    names = [observed[key] for key in ('ptr', 'first', 'second')]
    if len(set(names)) != 3 or any(re.search(rf'\b{re.escape(symbol)}\b', context) for symbol in names):
        return []
    addresses = [resolve(symbol) for symbol in names]
    if None in addresses or len(set(addresses)) != 3 or any(address % 4 for address in addresses):
        return []
    for symbol, base, offset in [(names[0], draft['owner'], draft['pointer']),
                                  (names[1], draft['data'], draft['first']),
                                  (names[2], draft['data'], draft['second'])]:
        address = resolve(base)
        if address is None or address + integer(offset) != resolve(symbol):
            return []
    pointer = f'M2C_FIELD(&{draft["owner"]}, void **, {draft["pointer"]})'
    first = f'M2C_FIELD(&{draft["data"]}, s32 *, {draft["first"]})'
    second = f'M2C_FIELD(&{draft["data"]}, s32 *, {draft["second"]})'
    body = source[part.opening + 1:part.end - 1]
    if body.count(pointer) != 2 or body.count(first) != 1 or body.count(second) != 1:
        return []
    body = body.replace(pointer, names[0]).replace(first, names[1]).replace(second, names[2])
    decl = f'extern void * volatile {names[0]};\nextern s32 {names[1]};\nextern s32 {names[2]};\n\n'
    fixed = edit(source, [(sig.start(), sig.start(), decl), (part.opening + 1, part.end - 1, body)])
    return [('measured_relocated_pointer_stores', fixed)]
