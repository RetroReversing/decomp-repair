"""A local read right after a call-free loop, copied into a temporary of its own before the loop.

A function that keeps its slot number in a saved register across the whole body (`var_s5`) and reads it once more after a
retry loop (`*(gTable + var_s5 * 0xFF8) = id;`) gets one instruction fewer than the target had: the target copied the slot
into an argument register before the loop (`move $a1, $s5`) and read the copy after it. The loop had no call, so the copy
lived in a call-clobbered register through it, and the loop's own pseudos (the id, two counters, the two hoisted constants)
took the registers around it as the target has them instead of one lower each: 830 -> 505 on a 384-instruction function
(isolated judge; no other family offered a child that moved that score).

For a `do`/`while`/`for` loop with no call in it, the first statement after the loop that reads an integer local `V` the loop
never mentions, the child declares `V_copy` of V's type, sets it right before the loop and reads it in that statement.
Only that one statement is changed, and only a `V` that is not assigned anywhere between the copy and the statement.
Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, _address_taken, edit
from .loop_address_hoist_repairs import _loops
from .pattern_repairs import close

FAMILY = 'post_loop_copy'
FAMILIES = (FAMILY,)
INTEGER = r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|[su](?:8|16|32)'
DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{INTEGER})[ \t]+(?P<name>{IDENT})[ \t]*;[ \t]*\n')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else'}
LIMIT = 4


def _statement_after(clean, at, end):
    """(start, end) of the statement that starts at or after `at` (skipping blanks), or None when it is a block or label."""
    start = at
    while start < end and clean[start] in ' \t\r\n}':
        start += 1
    if start >= end or clean[start] in '{':
        return None
    stop = clean.find(';', start, end)
    if stop < 0 or re.match(r'(?:if|for|while|do|switch|else|return|goto|break|continue|case|default)\b', clean[start:stop]):
        return None
    return start, stop + 1


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    body = clean[opening:end]
    if re.search(r'\b(?:asm|__asm__)\b|^\s*#', body, re.M):
        return []
    decls = {}
    for decl in DECL.finditer(clean, opening, end):
        if decl['name'] not in decls and not _address_taken(body, decl['name']):
            decls[decl['name']] = decl
    result = []
    for loop in _loops(clean, opening, end):
        text = clean[loop[0]:loop[1]]
        if re.search(rf'\b(?!(?:{"|".join(KEYWORDS)})\b){IDENT}\s*\(', re.sub(r'^\s*(?:for|while)\s*\(', '', text)):
            continue  # (a call in the loop: the copy would be saved across it)
        after = _statement_after(clean, loop[1], end)
        if not after:
            continue
        statement = clean[after[0]:after[1]]
        for var, decl in decls.items():
            if not re.search(rf'(?<![\w.>]){re.escape(var)}\b', statement) or re.search(rf'(?<![\w.>]){re.escape(var)}\b', text):
                continue
            if re.search(rf'(?<![\w.>]){re.escape(var)}\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=)', statement):
                continue
            copy = f'{var}_copy'
            if re.search(rf'\b{re.escape(copy)}\b', source):
                continue
            line = source.rfind('\n', 0, loop[0]) + 1
            lead = source[line:loop[0]]
            if lead.strip():
                continue
            edits = [(line, line, f'{lead}{copy} = {var};\n'), (decl.end(), decl.end(), f'{decl["indent"]}{decl["type"]} {copy};\n')]
            edits += [(after[0] + m.start(), after[0] + m.end(), copy)
                      for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', statement)]
            child = edit(source, edits)
            if (FAMILY, child) not in result:
                result.append((FAMILY, child))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
