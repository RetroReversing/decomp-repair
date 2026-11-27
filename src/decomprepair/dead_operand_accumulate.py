"""A sum's operand that is never read again, advanced in place first.

m2c reads `base += size; slot->second = ALIGN(base);` back as one expression, `... (base + size + 0xF) ...`, because
the advanced `base` is only ever used there. The compiler then adds into a scratch register, where the game added into
the saved register `base` lives in (`addu $s3,$s3,$s0` against `addu $s0,$s3,$s0`). When the left operand of such a sum
is a local that nothing reads after the statement, the child writes `base += size;` on the line before and the sum
reads `base`: the same value, and the dead local's new one is never seen. Not inside a loop, where the next pass would
read it. Measured on an N64 function (SN GCC 2.8.1): 460 -> 220, then `global_read_above_fill` 220 -> 0. Proposals
only; the byte judge decides."""
import re

from .integer_repair_support import DECL, IDENT, NUMBER, edit, view

FAMILY = 'dead_operand_accumulate'
FAMILIES = (FAMILY,)
LIMIT = 4
_SUM = re.compile(rf'\(\s*(?P<left>{IDENT})\s*\+\s*(?P<right>{IDENT}|{NUMBER})\s*(?=[+)])')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'\b(?:for|while|do|goto|volatile|asm|__asm__)\b', part.body):
        return []
    locals_ = {m['name'] for m in DECL.finditer(clean, part.opening, part.end)}
    out = []
    for hit in _SUM.finditer(clean, part.opening, part.end):
        left, right = hit['left'], hit['right']
        # a call's argument list or a cast's parenthesis is not a sum's
        if left not in locals_ or left == right or re.search(r'[\w\]]\s*$', clean[:hit.start()]):
            continue
        before = max(clean.rfind(mark, part.opening, hit.start()) for mark in ';{}')
        end = clean.find(';', hit.end())
        if before < 0 or end < 0:
            continue
        statement = clean[before + 1:end]
        assign = re.match(r'\s*(?P<dest>[^=;]*?[^=!<>+\-*/%&|^\s])\s*=(?!=)', statement)
        if not assign or '{' in statement or re.match(r'\s*(?:if|switch|else|return|case|default)\b', statement):
            continue
        # read once in the statement and never after it; `&left` anywhere could be read through the pointer
        if len(re.findall(rf'(?<![\w.>]){left}\b', statement)) != 1 or re.search(
                rf'(?<![\w.>]){left}\b', clean[end:part.end]) or re.search(rf'(?<![&])&\s*{left}\b', part.body):
            continue
        start = before + 1 + len(statement) - len(statement.lstrip())
        line = source.rfind('\n', 0, start) + 1
        if source[line:start].strip():
            continue
        indent = source[line:start]
        first = hit.start('left')
        out.append((FAMILY, edit(source, [(line, line, f'{indent}{left} += {right};\n'),
                                          (first, hit.end(), left + (' ' if clean[hit.end():].startswith('+') else ''))])))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',), 'order': 80}
