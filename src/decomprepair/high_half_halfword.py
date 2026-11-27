"""A local that holds the upper half of a 32-bit word, declared `u16`.

`t = word >> 16;` with an unsigned `word` can only hold a halfword, and a game that swapped a word's bytes through a
16-bit helper or local compiles differently from m2c's `u32 t;`: with the wide local the compiler folds `t`'s reads
back into shifts of `word` (or gives the value another register); with `u16 t` the value is one halfword of its own.

This changes the declaration of one such local to `u16`, only when the program stays the same: `t` is assigned once,
from a `>> 16` of an unsigned 32-bit value, its address is never taken, and every statement that reads it is an
integer assignment whose bits do not depend on the sign (`&`, `|`, `^`, `+`, `-`, `*`, `<<`, and a `>>` of `t`
itself), because `u16` promotes to `int` where the `u32` stayed unsigned.

Measured on one match (an N64 directory lookup that byte-swaps its count, `sn-n64-281 -G0 -mips3 -O2 -mfp64`):
the m2c draft 1330 -> 990 with this alone; without it the finished source scores 580.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'high_half_halfword'
FAMILIES = (FAMILY,)

UNSIGNED = r'(?:u32|unsigned\s+int|unsigned\s+long|unsigned)'
INTEGER = r'(?:u32|s32|u16|s16|u8|s8|unsigned\s+int|signed\s+int|unsigned|int)'


def _statements(body):
    return [piece.strip() for piece in re.split(r'[;{}]', body)]


def _sign_free(statement, local, body):
    """Whether `statement` computes the same bits when `local` promotes to int."""
    hit = re.fullmatch(rf'({IDENT})\s*(?:[-+*&|^]|<<)?=(?!=)\s*(.+)', statement, re.S)
    if not hit or not re.search(rf'(?<![\w.]){INTEGER}\s+{hit[1]}\b', body):
        return False
    value = hit[2].replace('->', '.')
    if re.search(r'[?/%!]|==|<=|>=|(?<!<)<(?!<)|(?<!>)>(?!>)|\b(?:f32|f64|float|double|s64|u64|long|sizeof)\b', value):
        return False
    if any(call not in ('if', 'while') for call in re.findall(rf'({IDENT})\s*\(', value)):
        return False
    for shift in re.finditer('>>', value):
        depth, at = 0, shift.start()
        while at > 0:  # back to the bracket that holds this shift: everything there is its left side
            char = value[at - 1]
            if char == '(' and depth == 0:
                break
            depth += (char == ')') - (char == '(')
            at -= 1
        left = value[at:shift.start()].strip()
        if left != local and re.search(rf'\b{local}\b', left):
            return False
    return True


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    body = part.body
    if re.search(r'\b(?:volatile|asm|__asm__)\b', body):
        return []
    parameters = part.clean[:part.opening]
    parameters = parameters[parameters.rfind(name):]
    declared = parameters + body
    out = []
    pattern = re.compile(rf'(?<=[;{{}}])\s*(?P<type>u32|s32|unsigned\s+int|unsigned|int)\s+(?P<name>{IDENT})\s*;')
    for hit in pattern.finditer(part.clean, part.opening, part.end):
        local = hit['name']
        word = re.escape(local)
        writes = re.findall(rf'(?<![\w.>]){word}\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{word}\b|\b{word}\s*(?:\+\+|--)', body)
        if len(writes) != 1 or re.search(rf'(?<![&\w)\]])\s*(?<!&)&\s*{word}\b\s*[),;]', body):
            continue
        assigned = re.search(rf'(?<![\w.>]){word}\s*=\s*(?:\(\s*(?P<cast>{UNSIGNED})\s*\)\s*)?(?P<word>{IDENT})\s*>>\s*(?:16|0x10)\s*;', body)
        if not assigned:
            continue
        if not assigned['cast'] and not re.search(rf'\b{UNSIGNED}\s+{assigned["word"]}\b', declared):
            continue
        rest = body[:assigned.start()] + body[assigned.end():]
        rest = re.sub(rf'\b(?:u32|s32|unsigned\s+int|unsigned|int)\s+{word}\s*;', ';', rest)
        readers = [line for line in _statements(rest) if re.search(rf'(?<![\w.>]){word}\b', line)]
        if not readers:
            continue
        # A signed local already read as int: only the unsigned one changes how its readers compute.
        if hit['type'] in ('s32', 'int'):
            if any(re.search(rf'&\s*{word}\b\s*[),]', line) for line in readers):
                continue
        elif not all(_sign_free(line, local, declared) for line in readers):
            continue
        out.append((FAMILY, edit(source, [(hit.start('type'), hit.end('type'), 'u16')])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
