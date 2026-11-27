"""A statement after a two-arm `if`/`else`, at the end of a loop body, written at the end of both arms.

    for (j = 0; j < 15; j++) {               for (j = 0; j < 15; j++) {
        if (edge) {                              if (edge) {
            load(0, 0);                              load(0, 0);
        } else {                       ->            tris(j, j + 1);
            load(s, t);                          } else {
        }                                            load(s, t);
        tris(j, j + 1);                              tris(j, j + 1);
    }                                            }
                                             }

The compiler cross-jumps the two copies back into one, but only after cse: with one copy after the join, `j + 1`
computed for it is reused for the loop's `j++` (`move` instead of `addiu`, and other registers). A 314-instruction
N64 terrain drawer (KMC GCC 2.7.2 `-O1`) matched with the copies (795 -> 0); `else_tail_into_arms` needs the arms to
end in the same call and `call_into_each_arm` yields nothing on a macro call after the arms.

Children (`tail_statement_into_arms`): each braced `if (c) { A } else { B }` followed by exactly one simple statement
(`...;`) and then the enclosing block's closing brace.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'tail_statement_into_arms'
FAMILIES = (FAMILY,)
LIMIT = 8


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    result = []
    for found in re.finditer(r'(?<![\w.])if\s*\(', clean[:span[1]]):
        if found.start() < opening:
            continue
        condition = close(clean, found.end() - 1, '(', ')')
        if condition is None:
            continue
        first = clean.find('{', condition)
        if first < 0 or clean[condition:first].strip() or re.search(r'\belse\s*$', clean[:found.start()]):
            continue
        first_end = close(clean, first, '{', '}')
        other = first_end is not None and re.match(r'\s*else\s*\{', clean[first_end:])
        if not other:
            continue
        second = first_end + other.end() - 1
        second_end = close(clean, second, '{', '}')
        if second_end is None:
            continue
        tail = re.match(r'(?P<space>\s*)(?P<statement>[^;{}]+;)\s*\}', clean[second_end:])
        if not tail or re.match(r'(?:return|break|continue|goto|if|else|for|while|do|switch|case|default)\b',
                                tail['statement']):
            continue
        a, b = second_end + tail.start('statement'), second_end + tail.end('statement')
        statement = source[a:b]
        text = source[:first_end - 1].rstrip() + f'\n    {statement}\n    ' + source[first_end - 1:second_end - 1].rstrip()
        text += f'\n    {statement}\n    ' + source[second_end - 1:second_end] + source[b:]
        result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
