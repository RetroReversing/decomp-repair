"""A word table m2c only saw through one address, indexed by hand in bytes, declared as the array it is.

m2c types a symbol it can't see as `extern M2C_UNK D;` (one word) and writes an element as `*((i * 4) + &D)` or
`*(s32 *)(t + &D)` with `t = i * 4`. C scales the offset by four again (`sll 4` where the target has `sll 2`).
`word_symbol_byte_offset` writes the sum in bytes, which computes the same address but keeps a constant in the index
inside it: `((x - 1) * 4) + (u8 *)&D` folds to `&D - 4` (an address the target never builds, where it has
`addiu -1; sll 2`). Declared `extern s32 D[];` and indexed, the `- 1` stays in the index.

word_symbol_array_index
    A lone-word symbol every use of which is `i * 4 + &D` (or a temporary set once to `i * 4`) is declared
    `extern s32 D[];` and read `D[i]` (`&D[i]` where only the address is taken). The other lone-word symbols added to
    an offset are written in bytes, `(u8 *)&D`, in the same child.

Seen on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 label update: 1160 with the table read in bytes and 0 indexed, the
rest of the source alike. One function, a controlled result. The judge decides; a symbol whose offset really counted
words computes something else here and does not match.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'word_symbol_array_index'
FAMILIES = (FAMILY,)

_DECLARATION = re.compile(r'(?m)^[ \t]*extern\s+(?P<type>s32|u32|int|M2C_UNK)\s+(?P<name>[A-Za-z_]\w*)\s*;')
_CAST = re.compile(r'\*\s*(?:\(\s*(?P<type>s8|u8|s16|u16|s32|u32|f32|int|M2C_UNK)\s*(?P<stars>\*+)\s*\)\s*)?$')
_FOUR = re.compile(r'(?P<index>.+?)\s*(?:\*\s*(?:4|0x4)|<<\s*2)', re.S)
WORDS = ('s32', 'u32', 'int', 'M2C_UNK')
_GROUP = re.compile(r'\([^()\[\]]*\)|\[[^()\[\]]*\]')
_MARK = re.compile(r'[()\[\];{},=]')


def _stripped(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _index(offset, body):
    """The element index a byte offset counts, or None when it is not plainly `index * 4`."""
    text = _stripped(offset)
    if re.fullmatch(r'[A-Za-z_]\w*', text):
        sets = re.findall(rf'(?<![\w.>]){text}\s*=(?!=)\s*([^;{{}}]+);', body)
        if len(sets) != 1:
            return None
        text = _stripped(sets[0])
    hit = _FOUR.fullmatch(text)
    if not hit:
        return None
    index = hit['index'].strip()
    bare, count = index.replace('->', '.'), 1
    while count:  # what stays outside every bracket must bind tighter than `*`
        bare, count = _GROUP.subn('_', bare)
    return None if re.search(r'[-+&|^<?]', bare) else _stripped(index)


def _sum(clean, start, stop, low):
    """(left, right) around the sum whose last term is the `&D` at [start, stop), or None."""
    after = re.match(r'\s*[),;]', clean[stop:])
    if not after or not re.search(r'\+\s*$', clean[low:start]):
        return None
    depth = 0
    for mark in reversed(list(_MARK.finditer(clean, low, start))):
        at, char = mark.start(), mark[0]
        if char in ')]':
            depth += 1
        elif char in '([':
            if not depth:
                return at + 1, stop
            depth -= 1
        elif not depth and (char != '=' or clean[at - 1] not in '=!<>'):
            return at + 1, stop
    return None


def _rewrite(text, clean, low, body, symbol, is_array, at, left, right):
    """(start, end, replacement) for the sum around the `&symbol` at `at`."""
    offset = text[left:at].rstrip()[:-1].strip()
    # a call's or a statement keyword's own parentheses stay
    enclosed = (clean[left - 1] == '(' and clean[right:].lstrip().startswith(')')
                and not re.search(r'[A-Za-z0-9_\]]\s*$', clean[max(low, left - 80):left - 1]))
    end = clean.index(')', right) + 1 if enclosed else right
    star = _CAST.search(clean, max(low, left - 80), left - 1) if enclosed else None
    if star and star['type'] is None:
        before = clean[max(low, star.start() - 80):star.start()].rstrip()
        if before and (before[-1].isalnum() or before[-1] in '_]'):
            star = None  # a product, not a read through the sum
    start = star.start() if star else (left - 1 if enclosed else left)
    index = _index(offset, body) if is_array else None
    kind = (star['type'] + (star['stars'][1:] and ' ' + star['stars'][1:])) if star and star['type'] else None
    if is_array:
        element = f'{symbol}[{index}]'
        if not star:
            new = f'&{element}'
        elif kind is None or kind in WORDS:
            new = element
        else:
            new = f'*({kind} *)&{element}'
    else:
        total = f'({offset} + (u8 *)&{symbol})'
        new = f'*({kind or "s32"} *){total}' if star else total
    if not star and not enclosed:
        new = (' ' if clean[left - 1] in '=,' else '') + new
        start = left
    return start, end if star or enclosed else right, new


def variants(source, name, header=''):
    part = view(source, name)
    if not part or '&' not in source:
        return []
    clean, low = part.clean, part.opening + 1
    body = clean[low:part.end - 1]
    declarations = {m['name']: m for m in _DECLARATION.finditer(clean[:part.opening])}
    sites, indexed = {}, []
    for symbol in declarations:
        found = []
        for hit in re.finditer(rf'(?<![\w&])&\s*{re.escape(symbol)}\b(?!\s*(?:\[|\.|->))', body):
            around = _sum(clean, low + hit.start(), low + hit.end(), low)
            if around:
                left, right = around
                offset = source[left:low + hit.start()].rstrip()[:-1].strip()
                found.append((left, right, low + hit.start(), offset))
        if not found:
            continue
        sites[symbol] = found
        mentions = len(re.findall(rf'(?<![\w.>]){re.escape(symbol)}\b', body))
        if mentions == len(found) and all(_index(offset, body) is not None for *_, offset in found):
            indexed.append(symbol)
    if not indexed:
        return []

    # innermost sums first, so an index that reads another table is rewritten before the sum around it
    text = source
    for symbol in sorted(sites):
        if symbol in indexed:
            text = re.sub(rf'(?m)^([ \t]*extern\s+){declarations[symbol]["type"]}(\s+{re.escape(symbol)})\s*;',
                          r'\1s32\2[];', text, count=1)
    for _ in range(8):  # sums nest (a table read inside another's index): innermost first, all of a depth at once
        part = view(text, name)
        clean, low = part.clean, part.opening + 1
        body = clean[low:part.end - 1]
        pending = []
        for symbol in sites:
            for hit in re.finditer(rf'(?<![\w&])&\s*{re.escape(symbol)}\b(?!\s*(?:\[|\.|->))', body):
                at = low + hit.start()
                if re.search(r'\(\s*u8\s*\*\s*\)\s*$', clean[low:at]):
                    continue
                around = _sum(clean, at, low + hit.end(), low)
                if around:
                    pending.append((around[1] - around[0], symbol, at, around))
        changes = []
        for _, symbol, at, (left, right) in sorted(pending):
            change = _rewrite(text, clean, low, body, symbol, symbol in indexed, at, left, right)
            if all(change[1] <= start or change[0] >= end for start, end, _ in changes):
                changes.append(change)
        if not changes:
            break
        text = edit(text, changes)
    return [(FAMILY, text)] if text != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
