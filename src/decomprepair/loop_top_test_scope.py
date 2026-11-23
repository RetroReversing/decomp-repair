"""A loop whose first statement is its exit test, with a local of its own declared in the body so the test stays at the top.

gcc 2.7.2's `expand_end_loop` (stmt.c) rolls a conditional exit found at the top of a loop to the bottom, "where it
will optimize together with the jump back", and so loses the test at the top that the game's code has (`bnez $a0, exit`
at the loop label and a `j` back from every path). It scans from the top of the body and stops at the first
`CALL_INSN`, `CODE_LABEL` or `NOTE_INSN_BLOCK_BEG`: a body that opens a block with a declaration puts a block note
before the test, nothing is rolled, and the loop keeps the shape the game had. m2c declares every local at the top of
the function, so a loop written as `for (;;) { if (done) break; ... }` is always rolled.

`variants` offers, for each `for (;;)` / `while (1)` / `while (...)` / `do` loop whose body begins with `if (...)
break;` and each plain local (no initialiser, not `volatile`/`register`) that is used only inside that body, the
declaration moved to the top of the body, one child per local (at most 4). In a 392-instruction object initialiser the
search loop that the target keeps unrolled went 4402 -> 3312 with the one local that only it used. That the rolling
rule is what decides this is read from the pinned compiler's stmt.c (the BLOCK_BEG break), not from a measurement of
the other compilers."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_top_test_scope'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'
LOOP = re.compile(r'\b(?:for\s*\(\s*;\s*;\s*\)|while\s*\([^;{}]*\)|do)\s*\{')
EXIT_FIRST = re.compile(r'\s*if\s*\([^;{}]*\)\s*(?:break\s*;|\{\s*break\s*;\s*\})')
DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>(?!return\b|goto\b|else\b)[A-Za-z_][\w \t]*?[ \t*]+)(?P<name>{IDENT})[ \t]*;[ \t]*\n')


def variants(source, name):
    """Proposals: one local's declaration moved to the top of a loop body whose first statement is the exit test."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    declarations = {}
    for hit in DECL.finditer(clean, span[0], span[1]):
        if re.search(r'\b(?:volatile|register|static|extern|typedef|return)\b', hit['type']):
            continue
        declarations.setdefault(hit['name'], hit)
    out = []
    for loop in LOOP.finditer(clean, span[0], span[1]):
        opening = loop.end() - 1
        closing = close(clean, opening, '{', '}')
        if not closing or not EXIT_FIRST.match(clean, opening + 1):
            continue
        body = clean[opening + 1:closing - 1]
        if re.match(rf'\s*(?:[A-Za-z_][\w \t]*?[ \t*]+){IDENT}[ \t]*;', body) and not EXIT_FIRST.match(body):
            continue  # (the body already opens with a declaration)
        for local, hit in declarations.items():
            if hit.start() > opening or not re.search(rf'\b{re.escape(local)}\b', body):
                continue
            uses = [m.start() for m in re.finditer(rf'\b{re.escape(local)}\b', clean[span[0]:span[1]])]
            inside = [m for m in re.finditer(rf'\b{re.escape(local)}\b', body)]
            if len(uses) != len(inside) + 1:
                continue
            line = source.find('\n', opening) + 1
            indent = re.match(r'[ \t]*', source[line:])[0] or hit['indent'] + '  '
            star = hit['type'].rstrip().endswith('*')
            declared = f"{indent}{hit['type'].rstrip()}{'' if star else ' '}{local};\n"
            if hit.end() <= line:
                out.append(source[:hit.start()] + source[hit.end():line] + declared + source[line:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 58}
