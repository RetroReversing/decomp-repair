"""A counter stepped inside the `if` that tests it, and the step written on its own line before the `if`.

`if (++count >= limit)` and `count++; if (count >= limit)` mean the same, and compile differently. With a narrow
counter that stays in a saved register, SN GCC 2.8.1 (`-G0 -mips3 -O2`) wrote the combined form as `addiu $v0, $s7, 1;
move $s7, $v0; andi $v0, $v0, 0xffff` (the sum goes through a temporary that the test then reads) and the split form as
the target's `addiu $s6, $s6, 1; andi $v0, $s6, 0xffff` (the counter stepped in place). On a 443-instruction N64
effect updater (a pool scan: `if (++k >= 501) { i = 501; break; }` with a `u16 k`) that was the last difference, 140 ->
0. That the temporary comes from how the increment's value is expanded is a hypothesis; the scores are measured, on one
function.

`postincrement_after_test` is the opposite end: `if (x++ != y)`, whose step belongs after the `if`.

`variants` rewrites an `if` whose condition *starts* with `++X`, `--X`, `(X += K)` or `(X -= K)` (so the step is the
first thing evaluated), or compares a plain value with one (`limit <= ++X`), where X is a name or a member chain. It
steps X before the `if` and tests X. One child per site, and one with every site.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'preincrement_before_test'
FAMILIES = (FAMILY,)
LVALUE = rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT})*'
VALUE = rf'(?:{LVALUE}|0[xX][0-9a-fA-F]+[uUlL]*|-?[0-9]+[uUlL]*)'
COMPARE = r'(?:==|!=|<=|>=|(?<![<>-])<(?![<=])|(?<![<>-])>(?![>=]))'
STEP = (rf'(?:(?P<prefix>\+\+|--)\s*(?P<target>{LVALUE})(?![\w\[(]|\s*(?:->|\.|\[|\())'
        rf'|\(\s*(?P<compound>{LVALUE})\s*(?P<op>[+-])=\s*(?P<amount>{VALUE})\s*\))')
# the step opens the condition: only parentheses (a cast would convert the value, so none) may come before it
FIRST = re.compile(rf'(?P<open>[\s(]*?){STEP}')
MIRRORED = re.compile(rf'\s*(?P<value>{VALUE})\s*{COMPARE}\s*{STEP}\s*')
LIMIT = 8


def _name(lvalue):
    return re.compile(rf'(?<![\w.>]){re.escape(lvalue)}(?!\w)')


def _sites(part):
    clean, limit = part.clean, part.end - 1
    for statement in re.finditer(r'\bif\s*\(', clean[part.opening + 1:limit]):
        start = part.opening + 1 + statement.start()
        previous = clean[:start].rstrip()
        if not previous or previous[-1] not in ';{}':
            continue  # `else if`, an unbraced body or a label: the step would run on other paths
        opening = part.opening + 1 + statement.end() - 1
        closing = close(clean, opening)
        if closing is None:
            continue
        condition = clean[opening + 1:closing - 1]
        found = MIRRORED.fullmatch(condition)
        if not found:
            found = FIRST.match(condition)
        if not found:
            continue
        lvalue = found['target'] or found['compound']
        rest = condition[found.end():]
        if re.search(rf'\bvolatile\b[^;{{}}]*\b{re.escape(lvalue.split("-")[0].split(".")[0].strip())}\b', clean):
            continue
        if 'value' in found.re.groupindex:
            if _name(lvalue).search(found['value']):
                continue
        else:
            # up to the first `&&`, `||`, `?` or `,` the other operand is unsequenced with the step
            operand = re.split(r'&&|\|\||\?|,', rest, maxsplit=1)[0]
            if _name(lvalue).search(operand):
                continue
        begin = found.start('prefix') if found['prefix'] else condition.index('(', found.start() if 'value' not in
                                                                              found.re.groupindex
                                                                              else found.end('value'))
        finish = found.end('target') if found['prefix'] else condition.index(')', found.end('amount')) + 1
        if found['prefix']:
            step = f'{lvalue}{found["prefix"]};'
        else:
            step = f'{lvalue} {found["op"]}= {found["amount"]};'
        line = clean.rfind('\n', 0, start) + 1
        lead = clean[line:start]
        text = f'{step}\n{lead}' if not lead.strip() else f'{step} '
        yield [(start, start, text), (opening + 1 + begin, opening + 1 + finish, lvalue)]


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    sites = list(_sites(part))
    children = []
    if len(sites) > 1:
        children.append((FAMILY, edit(source, [change for site in sites for change in site])))
    children += [(FAMILY, edit(source, site)) for site in sites]
    return children[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # registry.py
