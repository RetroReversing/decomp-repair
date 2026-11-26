"""A store's address computed into a local first, and the value's `|` chain associated to the left.

m2c writes `*(s32 *) (((char *) ((ch * 4) + entity)) + 0xF80) = (h << 16) | ((b2 << 8) | b3);` once its record pointer is
known. The compiler expands an assignment's address before its value, but the first scheduler is free to move the address's
two instructions behind the value's longer chain (a pointer load, a byte load and the shifts), and it did: `sll v1; lw v0;
sll a1; addu a1` where the target had `sll a1` first, a register fewer live across the value and the three loads' registers
in the other order. Staging the address in a local set at the top of the block, and writing the value's `|` chain the way a
left-to-right C reader gets it, `((h << 16) | (b2 << 8)) | b3`, together took 165 -> 115 on a 384-instruction function (the
staged address alone with the right-associated chain, 375; the left-associated chain alone, 175; isolated judge; no other
family offered a child that moved that score).

For a braced block of two or more statements that ends in a store through a computed address (an expression of at least two
names), whose names no earlier statement of the block assigns, the child sets `store_address = (u8 *) <address>;` as the
block's first statement and stores through `store_address + offset`; a second child also associates a right-nested `|` chain
of the stored value to the left. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'store_address_stage'
FAMILIES = (FAMILY,)
LOCAL = 'store_address'
TYPES = {'char', 's8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'long', 'void', 'unsigned'}
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
TARGET = re.compile(r'\(\s*(?P<type>[su](?:8|16|32)|int|long)\s*\*\s*\)\s*\((?P<inner>.*)\)', re.S)
OFFSET = re.compile(rf'\(\s*\(\s*char\s*\*\s*\)\s*(?P<addr>.+?)\s*\)\s*\+\s*(?P<off>{NUMBER})\s*', re.S)
LIMIT = 4


def _python_split(text, op='|'):
    """The operands of `text` at its top level."""
    parts, depth, begin = [], 0, 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if char == op and depth == 0 and text[at:at + 2] != op * 2:
            parts.append(text[begin:at])
            begin = at + 1
    parts.append(text[begin:])
    return [p.strip() for p in parts]


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text, op='|'):
        # (a bracket as `op`: this loop counts the depth first and then tests, so it can split at one; the kernel never does)
        found = NotImplemented if op in ('(', ')') else _scan.top_offsets(text, op, 1)
        if found is NotImplemented:
            return _python_split(text, op)
        parts, begin = [], 0
        for at in found:
            if text[at:at + 2] != op * 2:
                parts.append(text[begin:at])
                begin = at + 1
        parts.append(text[begin:])
        return [part.strip() for part in parts]


def _unparen(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _stores(clean, opening, end):
    """Each `*((T *) (((char *) ADDR) + OFF)) = VALUE;` as a dict of spans and texts."""
    for hit in re.finditer(r'(?<![\w)\]])\*\s*\(', clean[opening:end]):
        start = opening + hit.start()
        paren = opening + hit.end() - 1
        stop = close(clean, paren)
        if not stop:
            continue
        target = TARGET.fullmatch(clean[paren + 1:stop - 1].strip())
        if not target:
            continue
        offset = OFFSET.fullmatch(target['inner'].strip())
        eq = re.match(r'\s*=(?!=)\s*', clean[stop:end])
        if not offset or not eq:
            continue
        value_start = stop + eq.end()
        semicolon = clean.find(';', value_start, end)
        if semicolon < 0 or '{' in clean[value_start:semicolon]:
            continue
        yield {'start': start, 'target_end': stop, 'addr': offset['addr'], 'off': offset['off'], 'type': target['type'],
               'value_start': value_start, 'value_end': semicolon, 'value': clean[value_start:semicolon].strip()}


def left_associate(value):
    """`(s32) (X | (Y | Z))` as `(s32) ((X | Y) | Z)`, or None when the value is not such a chain."""
    cast = re.match(r'(\(\s*[su](?:8|16|32)\s*\)\s*)?(.*)', value.strip(), re.S)
    inner = _unparen(cast[2])
    first = _split(inner)
    if len(first) != 2:
        return None
    rest = _split(_unparen(first[1]))
    if len(rest) < 2:
        return None
    chain = first[0]
    for part in rest:
        chain = f'({chain} | {part})'
    return f'{cast[1] or ""}{chain}'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    if re.search(r'\b(?:asm|__asm__)\b|^\s*#', clean[opening:end], re.M) or re.search(rf'\b{LOCAL}\b', source):
        return []
    decl = re.search(r'(?m)^([ \t]*)[A-Za-z_][\w ]*[ \t]+\**[ \t]*\w+[ \t]*;[ \t]*\n', source[opening:end])
    if not decl:
        return []
    declare = (opening + decl.end(), opening + decl.end(), f'{decl[1]}u8 *{LOCAL};\n')
    result = []
    for store in _stores(clean, opening, end):
        names = set(re.findall(IDENT, store['addr'])) - TYPES
        if len(names) < 2 or not re.search(r'[*+]', store['addr']):
            continue
        # the block this store ends: at least one statement above it, none of which assigns a name of the address
        depth, at = 0, store['start']
        while at > opening:
            at -= 1
            depth += (clean[at] == '}') - (clean[at] == '{')
            if depth < 0:
                break
        if depth >= 0 or clean[store['value_end'] + 1:].lstrip()[:1] != '}':
            continue
        earlier = clean[at + 1:store['start']]
        if ';' not in earlier or any(re.search(rf'(?<![\w.>]){re.escape(n)}\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=)', earlier)
                                    for n in names):
            continue
        line = source.find('\n', at) + 1
        indent = re.match(r'[ \t]*', source[line:]).group()
        stage = (line, line, f'{indent}{LOCAL} = (u8 *) {store["addr"]};\n')
        target = (store['start'], store['target_end'], f'*(({store["type"]} *) ({LOCAL} + {store["off"]}))')
        value = (store['value_start'], store['value_end'], store['value'])
        result.append((FAMILY, edit(source, [stage, target, declare])))
        associated = left_associate(store['value'])
        if associated:
            result.append((FAMILY, edit(source, [stage, target, (*value[:2], associated), declare])))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
