"""A value computed once and added to several totals, wrapped in a one-shot scope that changes what the registers weigh.

GCC 2.x counts every reference to a pseudo register once per loop depth (flow.c: `REG_N_REFS += loop_depth`; hypothesis,
read from the allocation tables rather than the compiler source), and global.c hands the saved registers out in order of
`floor_log2(uses) * uses / live_length`. A `do { ... } while (0)` still counts as a loop depth there, so the statements
inside it weigh double without any runtime iteration. The loop-weight family (`loop_weight_scope`) wraps a lone
`x += y;` or a load; the run

    adv = font->glyphs[idx * 5 + 2] + font->extra;
    width += adv;
    total += adv;

at the end of a switch arm needed all three statements inside one wrapper: the same text with only the two additions
wrapped scored 30 (and deeper wrappers 1880, 105, 1695), the value assignment included in a depth-one wrapper scored 0
(KMC GCC 2.7.2, a text-measuring function whose character index and the zero-extended character shared a priority to
within 0.03, 1.800 against 1.778, so the pair took each other's saved registers: with the run's references doubled the
index outranked the character, the target's order). The assignment is part of the run because its destination's
references are the ones that have to outweigh a neighbour's.

`accumulation_run_scope`: a local assigned once from an expression and then added into one or more variables in the
statements right after it, all inside one block, wrapped as `do { ... } while (0);` at depth one and two. The text is
the same program: no branch or label crosses the wrapper and nothing declared inside it is read outside."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'accumulation_run_scope'
FAMILIES = (FAMILY,)
LIMIT = 6
RUN = re.compile(r'(?<=[;{}])(?P<lead>\s*)(?P<run>(?P<d>' + IDENT + r')\s*=\s*(?P<value>[^;{}=][^;{}]*);(?:\s*' + IDENT + r'\s*\+=\s*(?P=d)\s*;)+)')
CONTROL = re.compile(r'\b(?:break|continue|goto|return|case|default|asm|__asm__|volatile)\b')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for hit in RUN.finditer(part.clean, part.opening, part.end):
        d = hit['d']
        run = hit['run']
        if CONTROL.search(run) or re.search(r'(?<![\w.>])' + re.escape(d) + r'\b\s*(?:\+\+|--)', run):
            continue
        # a local scalar declared in the function head, not a parameter or a global
        if not re.search(r'(?m)^[ \t]*(?:(?:unsigned|signed)\s+)?\w+\s+' + re.escape(d) + r'\s*;', part.clean[part.opening:part.end]):
            continue
        before = part.clean[part.opening:hit.start('run')].rstrip()
        if re.search(r'\bdo\s*\{$', before):
            continue
        # the value is only read by the additions (and nowhere after the block it sits in would need it)
        for depth in (1, 2):
            wrapped = 'do { ' * depth + run + ' } while (0);' * depth
            out.append((FAMILY, edit(source, [(hit.start('run'), hit.end('run'), wrapped)])))
        if len(out) >= LIMIT:
            break
    return out
