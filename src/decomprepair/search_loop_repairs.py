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



def _standalone_copy(source, clean, header, span, hit):
    """A result copy immediately before a plain field comparison is dead on failure."""
    node, result = hit['node'], hit['result']
    before = clean[hit.start('before'):hit.end('before')]
    if (node == result or not re.fullmatch(rf'\s*{re.escape(result)}\s*=\s*{re.escape(node)}\s*;\s*', before)
            or re.search(r'/[*/]|#', source[hit.start():hit.end()])):
        return False
    number = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
    condition = re.fullmatch(rf'\s*M2C_FIELD\(\s*{re.escape(node)}\s*,\s*s32\s*\*\s*,\s*{number}\s*\)'
                             rf'\s*!=\s*(?P<key>[A-Za-z_]\w*)\s*', hit['condition'])
    next_node = re.fullmatch(rf'\s*M2C_FIELD\(\s*{re.escape(node)}\s*,\s*void\s*\*\*\s*,\s*{number}\s*\)\s*', hit['next'])
    if not condition or not next_node:
        return False
    key = condition['key']
    if (key in (node, result) or re.search(rf'&\s*(?:{re.escape(node)}|{re.escape(result)}|{re.escape(key)})\b', clean[span[0]:span[1]])
            or any(len(re.findall(rf'\bvoid\s*\*\s*{re.escape(v)}\b', clean[span[0]:span[1]])) != 1 for v in (node, result))
            or not re.search(rf'\bs32\s+{re.escape(key)}\s*(?:,|\))', clean[span[0]:clean.find('{', span[0], span[1])])):
        return False
    context = source + '\n' + header
    if re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return False
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (node, result, key) for line in macros):
        return False
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    return len(definitions) == 1 and bool(re.fullmatch(
        r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
        r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0]))

def variants(source, name, header=''):
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
        if len(re.findall(r'\bgoto\s+' + hit['loop'] + r'\b', clean[opening:end])) != 1:
            continue
        before_text = source[hit.start('before'):hit.end('before')]
        if len(copy) == 1:
            condition = condition[:copy[0].start()] + condition[copy[0].end():]
        elif not copy and _standalone_copy(source, clean, header, span, hit):
            before_text = ''
        else:
            continue
        rest = clean[opening:hit.start()] + clean[hit.end():end]
        indent, inner = hit['indent'], hit['indent'] + '    '
        before = ''.join(inner + line.strip() + '\n' for line in before_text.splitlines()
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
