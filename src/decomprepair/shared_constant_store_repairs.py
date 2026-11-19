"""A store of a constant at each of its sites, where m2c merged them through a label.

gcc cross-jumps identical tails: two cases that each store a constant and return become one store the second jumps
to, the constants loaded before it. m2c reads that back as a variable and a `goto`:

    case 0:  ... v = 1;
    block_30:
                 M2C_FIELD(arg0, s16 *, 0x7A) = v;
             }
             return;
    case 3:  ... v = 2;
             goto block_30;

An N64 function was 96.6% so and exact with the store written at each site (`... = 1;` and `... = 2; return;`). Offered
when the label's statement is the variable's only use, it uses the variable once, and only closing braces and a
`return;` follow it; the jump's site then returns (or breaks, a second proposal).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'shared_constant_store'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    shape = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<v>' + IDENT + r')\s*=\s*(?P<k>' + NUMBER + r')\s*;[ \t]*\n'
                       r'(?P<label>' + IDENT + r'):[ \t]*\n'
                       r'(?P<sindent>[ \t]*)(?P<stmt>[^\n;{}]*;)[ \t]*\n'
                       r'(?P<after>(?:[ \t]*\}[ \t]*\n)*[ \t]*return\s*;)')
    for hit in shape.finditer(clean, opening, end):
        var, label, stmt = hit['v'], hit['label'], source[hit.start('stmt'):hit.end('stmt')]
        uses = re.findall(r'(?<![\w.>])' + var + r'\b', stmt)
        if len(uses) != 1 or re.search(r'(?<![\w.>])' + var + r'\s*=(?!=)', stmt):
            continue
        jumps = list(re.finditer(r'(?m)^(?P<indent>[ \t]*)' + var + r'\s*=\s*(?P<k>' + NUMBER + r')\s*;\s*\n[ \t]*goto\s+'
                                 + label + r'\s*;[ \t]*\n', clean[opening:end]))
        mentions = re.findall(r'(?<![\w.>])' + var + r'\b', clean[opening:end])
        # the declaration, the label's site (assignment and use) and each jump's assignment
        if not jumps or len(mentions) != 3 + len(jumps):
            continue
        if len(re.findall(r'\bgoto\s+' + label + r'\b', clean[opening:end])) != len(jumps):
            continue
        for ending in ('return;', 'break;'):
            text = source
            for jump in reversed(jumps):
                a, b = opening + jump.start(), opening + jump.end()
                own = re.sub(r'(?<![\w.>])' + var + r'\b', source[a + jump.start('k') - jump.start():
                                                                    a + jump.end('k') - jump.start()], stmt)
                text = text[:a] + f"{jump['indent']}{own}\n{jump['indent']}{ending}\n" + text[b:]
            site = re.sub(r'(?<![\w.>])' + var + r'\b', source[hit.start('k'):hit.end('k')], stmt)
            text = (text[:hit.start()] + f"{hit['sindent']}{site}\n" + text[hit.start('after'):])
            declared = re.search(r'(?m)^[ \t]*[\w ]+?[\s*]+' + var + r'\s*;[ \t]*\n', text[opening:])
            if declared:
                text = text[:opening + declared.start()] + text[opening + declared.end():]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:2]
