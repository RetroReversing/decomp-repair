"""A later test's `p->member + K` held in a local ahead of the test before it.

GCC 2.x expands a condition where it stands, so in

    if (addr < p->start) break;
    else if (end <= p->start + 0x400) { ... }

the add comes after the first test's branch. A target that loads the member once and has the add *before* the first
`slt` (`lw; addiu; slt; bnez; slt`) computed the sum in a local first:

    limit = p->start + 0x400;
    if (addr < p->start) break;
    else if (end <= limit) { ... }

On a list search of 106 instructions (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) this was the last difference
(215 -> 0). The add moves ahead of a test, so it must be safe to run when that test leaves: the first test already
reads through the same base pointer, and every operand is an integer by its declaration. One site per child; the
judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'later_test_sum_stage'
FAMILIES = (FAMILY,)
LIMIT = 8
LOCAL = '__stage_sum'
_MEMBER = rf'(?P<base>{IDENT})\s*->\s*(?P<member>{IDENT})'
_SUM = re.compile(rf'(?<![\w.>\]\)*&+\-])(?:{_MEMBER}\s*[+-]\s*{NUMBER}|{NUMBER}\s*\+\s*(?P<base2>{IDENT})\s*->\s*(?P<member2>{IDENT}))(?![\w.\[(*/]|\s*(?:->|[.\[(*/%+\-]|<<|>>))')
_JUMP = re.compile(r'\s*(?:\{\s*)?(?:break|continue|return\b[^;{}]*|goto\s+' + IDENT + r')\s*;(?:\s*\})?')
_IF = re.compile(r'\bif\s*\(')
_INTEGER = r'(?:(?:unsigned|signed)(?:\s+(?:char|short|int|long))?|[su](?:8|16|32)|char|short|int|long)'


def _integer_member(member, context):
    """Every declaration of a field or variable called `member` has an integer type, and there is one."""
    declared = re.findall(rf'([A-Za-z_][\w]*(?:\s+[A-Za-z_]\w*)*)(\s*\**\s*)\b{re.escape(member)}\s*(?:;|,)', context)
    declared = [(kind, stars) for kind, stars in declared if kind.split()[0] not in ('return', 'goto', 'else')]
    return bool(declared) and all('*' not in stars and re.fullmatch(_INTEGER, kind.split('struct ')[-1])
                                  for kind, stars in declared)


def _sites(part, header):
    clean, context = part.clean, header + '\n' + part.clean
    for first in _IF.finditer(clean, part.opening + 1, part.end):
        before = clean[part.opening:first.start()].rstrip()
        if not before.endswith(('{', ';', '}')):
            continue  # `else if`, or the unbraced body of a loop or another test
        paren = first.end() - 1
        stop = close(clean, paren)
        if not stop:
            continue
        jump = _JUMP.match(clean, stop)
        if not jump:
            continue
        second = re.compile(r'\s*(?:else\s+)?if\s*\(').match(clean, jump.end())
        if not second:
            continue
        opened = second.end() - 1
        ended = close(clean, opened)
        if not ended:
            continue
        condition = clean[opened + 1:ended - 1]
        if re.search(r'&&|\|\||\?|\+\+|--|(?<![<>=!])=(?!=)', condition):
            continue
        for hit in _SUM.finditer(clean, opened + 1, ended - 1):
            base = hit['base'] or hit['base2']
            member = hit['member'] or hit['member2']
            if not re.search(rf'(?<![\w.>]){re.escape(base)}\s*->', clean[paren:stop]):
                continue
            if _integer_member(member, context):
                yield first.start(), hit


def variants(source, name, header=''):
    part = view(source, name)
    if not part or LOCAL in source or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    out = []
    for start, hit in _sites(part, header):
        line = source.rfind('\n', 0, start) + 1
        indent = source[line:start] if not source[line:start].strip() else ''
        opening = part.opening + 1
        out.append((FAMILY, edit(source, [(opening, opening, f'\n  int {LOCAL};'),
                                          (start, start, f'{LOCAL} = {source[hit.start():hit.end()]};\n{indent}'),
                                          (hit.start(), hit.end(), LOCAL)])))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
