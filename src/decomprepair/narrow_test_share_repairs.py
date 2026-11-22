"""A signed narrow cast of one variable tested twice, computed once in a local.

`((s8) flag) == 0` and, a few statements later, `((s8) flag) != 0` read the variable twice. gcc 2.7.2 folds a
comparison of a narrowing cast with zero into a test of the low byte (`lbu` and a branch), so neither test
sign-extends, and the two tests reload the byte. A local `sx = (s8) flag;` assigned before the first test and tested at
both keeps one sign-extended value (`lbu $t0; sll $v0,$t0,24; sra $v1,$v0,24`, then `bnez $v1` and later `beqz $v1`),
which is what the target of a 374-instruction N64 effect spawner (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) has: the
sign extension was two missing instructions and moved every later branch offset. Hypothesis, not confirmed in the
compiler source: fold-const narrows the comparison before expansion, the local's assignment is expanded as a real
conversion before the tests exist.

`narrow_test_share` takes two reads of `(s8) x` / `(s16) x` of one local or parameter `x` in one block, with no write
to `x`, no label and no jump between them, and offers a new `s32` local assigned right before the statement of the
first read and used at both. The local is declared after the function's last leading declaration (declaration order is
the order of the pseudos, which reload follows for stack slots). The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_test_share'
FAMILIES = (FAMILY,)
LIMIT = 6
CAST = re.compile(rf'\(\s*(?P<type>s8|s16|signed\s+char|signed\s+short|char|short)\s*\)\s*(?P<name>{IDENT})\b(?!\s*[\[(.]|\s*->)')
DECLARATION = re.compile(rf'\s*(?:typedef\s+)?(?:(?:(?:struct|union)\s*{IDENT}?\s*{{[^{{}}]*}}\s*{IDENT}?)|'
                         rf'(?:(?:unsigned|signed|const|register|volatile|struct|union)\s+)*{IDENT}(?:\s+{IDENT})?[\s*]+{IDENT}(?:\s*\[[^\]]*\])*(?:\s*=[^;{{}}]*)?)\s*;')
CONTROL = {'return', 'goto', 'break', 'continue', 'case', 'default', 'else', 'do', 'if', 'while', 'for', 'switch'}


def _leading_declarations_end(clean, opening, end):
    cursor = opening + 1
    while True:
        match = DECLARATION.match(clean, cursor, end)
        if not match or re.match(r'\s*(?:' + '|'.join(CONTROL) + r')\b', match[0]):
            return cursor
        cursor = match.end()


def _statement_start(clean, position, floor):
    depth = 0
    for index in range(position - 1, floor, -1):
        char = clean[index]
        if char == ')':
            depth += 1
        elif char == '(':
            depth -= 1
        elif depth <= 0 and char in ';{}':
            return index + 1
    return floor + 1


def _same_block(clean, first, second):
    """True when no brace closes between the reads that the first one's block does not also hold."""
    depth = 0
    for char in clean[first:second]:
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0:
                return False
    return True


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    fresh = '__repair_narrow'
    if fresh in source:
        return []
    top = _leading_declarations_end(clean, part.opening, part.end)
    reads = [hit for hit in CAST.finditer(clean, top, part.end)]
    result = []
    for index, first in enumerate(reads):
        for second in reads[index + 1:]:
            if (first['name'], re.sub(r'\s+', ' ', first['type'])) != (second['name'], re.sub(r'\s+', ' ', second['type'])):
                continue
            between = clean[first.end():second.start()]
            variable = re.escape(first['name'])
            if (re.search(rf'(?<![\w.>]){variable}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{variable}\b|\b{variable}\s*(?:\+\+|--)|&\s*{variable}\b', between)
                    or re.search(r'\b(?:goto|return|case|default)\b|(?<![\w.>?:])' + IDENT + r'\s*:(?!:)', between)
                    or not _same_block(clean, first.start(), second.start())):
                continue
            start = _statement_start(clean, first.start(), part.opening)
            while clean[start:start + 1].isspace():
                start += 1
            indent = re.search(r'[ \t]*$', clean[:start])[0]
            local = f'{fresh}_{first["name"]}'
            if local in source:
                continue
            edits = [(first.start(), first.end(), local), (second.start(), second.end(), local), (start, start, f'{local} = {first.group()};\n{indent}'),
                     (top, top, f'\n  s32 {local};')]
            result.append((FAMILY, edit(source, edits)))
            break  # the nearest second read of this first read
        if len(result) >= LIMIT:
            break
    return result
