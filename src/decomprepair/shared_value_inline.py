"""Every temporary that only holds an index, its scaled form or the element it reads, written out at each read.

m2c names the values the compiler's reuse kept in registers: the masked index, the index times four, the element
read from a local copy of a table. The game wrote `table[i]` at each test:

    temp_v0 = i;                                      if ((u32) (ids.data[i] - 0x13A) < 3U) {
    temp_a0 = temp_v0 * 4;                      ->        name = *(s32 *)((i * 4) + names);
    temp_v1 = ids.data[temp_v0];                      } else if (ids.data[i] == 0x13E) {
    if ((u32) (temp_v1 - 0x13A) < 3U) {
        name = *(s32 *)(temp_a0 + names);

Inlining one of them alone changes nothing or scores worse, since the others still tie the registers, so the child
writes out all of them together. `single_use_inline` takes a value read once and `reread_temporary_inline` one with a
call between the set and the last read; these are read by the tests of an `if` chain.

A local qualifies when it is a 32-bit integer set by exactly one statement and read only after it inside that
statement's block, its value is made of literals, parameters, other integer locals and elements of locals (no call,
no dereference, no global), and nothing in it is assigned, stepped or has its address taken from the set on.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 routine (230 instructions) that looks an id up in a local copy of a
table and tests it in a long `if` chain.

shared_value_inline
    Every qualifying local's value written at its reads, the set and the declaration removed, in one child.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_value_inline'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_DECL = re.compile(rf'(?m)^[ \t]*(?:s32|u32|int)\s+(?P<name>{_ID})\s*;[ \t]*\n')
_VALUE = re.compile(r'(?:[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)?|0[xX][0-9A-Fa-f]+|\d+|<<|>>|[\s+\-*&|\[\]()])+')


def _block_close(clean, position, opening, end):
    """Where the innermost block around `position` closes."""
    depth = 0
    for at in range(position, end):
        if clean[at] == '{':
            depth += 1
        elif clean[at] == '}':
            if not depth:
                return at
            depth -= 1
    return end


def _assigned(word, text):
    return re.search(rf'(?<![\w.>]){word}(?:\s*\.\s*{_ID})?(?:\s*\[[^\]]*\])?\s*(?:=(?!=)|[-+*/|&^]=|<<=|>>=|\+\+|--)|'
                     rf'(?:\+\+|--|(?<![\w)\]\s&])\s*&(?!&)|\(\s*&(?!&)|,\s*&(?!&))\s*{word}\b', text)


def _one(source, name):
    """`source` with the first qualifying local written out, or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    header = clean[span[0]:opening]
    body = clean[opening:end]
    parameters = set(re.findall(rf'\b(?:s32|u32|int|s16|u16|s8|u8)\s+({_ID})\s*(?=[,)])', header))
    locals_ = {m[1] for m in re.finditer(
        rf'(?m)^[ \t]*(?!return\b|goto\b|else\b){_ID}[ \t]+({_ID})[ \t]*(?:\[[^\]]*\])?[ \t]*;', body)}
    for declared in _DECL.finditer(clean, opening, end):
        local = declared['name']
        sets = list(re.finditer(rf'(?m)^[ \t]*{local}\s*=(?!=)\s*(?P<value>[^;{{}}\n]+);[ \t]*\n', clean[:end]))
        sets = [s for s in sets if s.start() > opening]
        if len(sets) != 1:
            continue
        found = sets[0]
        value = found['value'].strip()
        if not _VALUE.fullmatch(value) or re.search(r'(?:^|[(+\-*&|<>\[])\s*[*&]|[A-Za-z_]\w*\s*\(', value):
            continue
        words = {m[1] for m in re.finditer(rf'(?<![\w.])({_ID})', value)} - {'s32', 'u32', 's16', 'u16', 's8', 'u8'}
        if local in words or not words <= parameters | locals_:
            continue
        rest = clean[found.end():end]
        if any(_assigned(word, rest) for word in words) or _assigned(local, clean[opening:found.start()] + rest):
            continue
        # an array used bare decays to its address, which a call may then write through
        if any(re.search(rf'(?<![\w.]){word}\.{_ID}\b(?!\s*\[)', body) for word in words):
            continue
        stop = _block_close(clean, found.end(), opening, end)
        mentions = [m for m in re.finditer(rf'(?<![\w.>]){local}\b', clean[:end])
                    if m.start() > opening and not declared.start() <= m.start() < declared.end()
                    and not found.start() <= m.start() < found.end()]
        if not mentions or any(not found.end() <= m.start() < stop for m in mentions):
            continue
        written = source[found.start('value'):found.end('value')].strip()
        if not re.fullmatch(rf'\w+(?:\.{_ID})?(?:\[[^\[\]]*\])?', written):
            written = f'({written})'
        edits = [(declared.start(), declared.end(), ''), (found.start(), found.end(), '')]
        edits += [(m.start(), m.end(), written) for m in mentions]
        text = source
        for a, b, replacement in sorted(edits, reverse=True):
            text = text[:a] + replacement + text[b:]
        return text
    return None


def variants(source, name):
    text, changed = source, 0
    for _ in range(24):
        step = _one(text, name)
        if step is None:
            break
        text, changed = step, changed + 1
    return [(FAMILY, text)] if changed > 1 else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
