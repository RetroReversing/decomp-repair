"""m2c's `goto` form of a list search, written as the `while` loop that returns what it finds.

A loop walking a linked list until a node matches comes back from m2c as a label inside an `if`, the found node
copied into the result inside the failing condition:

    var_v0 = NULL;
    if (var_a2 != NULL) {
    loop_1:
        temp_v0 = M2C_FIELD(var_a2, void **, 0x3C);
        if ((temp_v0 == NULL) || (...) || (var_v0 = var_a2, (... != arg1))) {
            var_a2 = M2C_FIELD(var_a2, void **, 0x10);
            var_v0 = NULL;
            if (var_a2 != NULL) {
                goto loop_1;
            }
        }
    }
    return var_v0;

gcc keeps that result in its own register; the game returned the node from the loop. As `while (var_a2 != NULL) {
...; if (!(<the condition without the copy>)) return var_a2; var_a2 = next; } return NULL;` an N64 function was
exact (230 before).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'goto_search_loop'
FAMILIES = (FAMILY,)

SHAPE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<result>[A-Za-z_]\w*) = (?:NULL|0);[ \t]*\n'
    r'[ \t]*if \((?P<node>[A-Za-z_]\w*) != (?:NULL|0)\) \{[ \t]*\n'
    r'[ \t]*(?P<loop>[A-Za-z_]\w*):[ \t]*\n'
    r'(?P<before>(?:[^\n:{}]*;[ \t]*\n)*?)'
    r'[ \t]*if \((?P<condition>.*)\) \{[ \t]*\n'
    r'[ \t]*(?P=node) = (?P<next>[^;\n]+);[ \t]*\n'
    r'[ \t]*(?P=result) = (?:NULL|0);[ \t]*\n'
    r'[ \t]*if \((?P=node) != (?:NULL|0)\) \{[ \t]*\n'
    r'[ \t]*goto (?P=loop);[ \t]*\n'
    r'[ \t]*\}[ \t]*\n[ \t]*\}[ \t]*\n[ \t]*\}[ \t]*\n'
    r'[ \t]*return (?P=result);[ \t]*\n')


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
    for hit in SHAPE.finditer(clean, opening, end):
        node, found = hit['node'], hit['result']
        condition = source[hit.start('condition'):hit.end('condition')]
        copy = list(re.finditer(r'(?<![\w.>])' + found + r'\s*=\s*' + node + r'\s*,\s*', condition))
        if len(copy) != 1 or len(re.findall(r'\bgoto\s+' + hit['loop'] + r'\b', clean[opening:end])) != 1:
            continue
        condition = condition[:copy[0].start()] + condition[copy[0].end():]
        rest = clean[opening:hit.start()] + clean[hit.end():end]
        indent, inner = hit['indent'], hit['indent'] + '    '
        before = ''.join(inner + line.strip() + '\n' for line in source[hit.start('before'):hit.end('before')].splitlines()
                         if line.strip())
        loop = (f'{indent}while ({node} != NULL) {{\n' + before
                + f'{inner}if (!({condition})) {{\n{inner}    return {node};\n{inner}}}\n'
                + f'{inner}{node} = {source[hit.start("next"):hit.end("next")].strip()};\n'
                + f'{indent}}}\n{indent}return NULL;\n')
        text = source[:hit.start()] + loop + source[hit.end():]
        # the result variable is gone when nothing else used it
        declaration = r'(?m)^[ \t]*[\w ]+?[\s*]+' + found + r'\s*;[ \t]*\n'
        if not re.search(r'(?<![\w.>])' + found + r'\b', re.sub(declaration, '', rest)):
            text = re.sub(declaration, '', text, count=1)
        result.append((FAMILY, text))
    return result[:2]
