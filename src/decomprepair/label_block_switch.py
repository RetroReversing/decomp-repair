"""An if-tree that jumps to one shared block, written as the `switch` whose cases name the values that reach it.

m2c writes a `switch` the compiler lowered to a compare tree (`beq 2`, `slti 3`, `beqz`, `li 4; beq`, `li 8; bne`) as
nested `if`s whose arms `goto` a label inside one `else`, and spells `x == 4` through an identity helper to stop the
compiler folding `a || b`. A real `switch (x) { case 0: case 2: case 4: case 8: refresh(); break; }` lowers to the
target's tree, with branches instead of m2c's value arithmetic (`xori; sltiu; or`): 1170 -> 770 in a 970-instruction
N64 state-machine handler (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), the last of the tail's differences.
`compare_tree_switch` reads trees without the `goto` and the label.

`variants` finds a top-level `if` statement (one statement per line, braces on lines of their own) in which every
condition compares one integer local with constants (`==`, `!=`, `<`, `>=`, ... joined by `!`, `&&`, `||`, casts and
`inline_fn*(...)` identity helpers allowed) and every other statement is a `goto` to one label or the label's own
block. It runs the tree for each value of the local from -8 to 63, and when at most 16 values reach the label offers
`switch (x) { case a: case b: <the label block> break; }` in its place. One child per tree, at most 2. A candidate
rewrite: the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines

FAMILY = 'label_block_switch'
FAMILIES = (FAMILY,)
LIMIT = 2
DOMAIN = range(-8, 64)
MAX_CASES = 16
CAST = re.compile(r'\(\s*(?:int|s32|u32|unsigned(?:\s+int)?|s16|u16|s8|u8|signed\s+int)\s*\)')
LABEL = re.compile(r'([A-Za-z_]\w*)\s*:')


class Stop(Exception):
    pass


def _python(condition, name):
    text = CAST.sub(' ', condition)
    text = re.sub(r'\binline_fn\w*\s*\(', '(', text)
    text = text.replace('&&', ' and ').replace('||', ' or ')
    text = re.sub(r'!(?!=)', ' not ', text)
    text = re.sub(rf'(?<![\w.]){re.escape(name)}\b', 'x', text)
    text = re.sub(r'(0[xX][0-9A-Fa-f]+|\d+)[uUlL]*', lambda m: str(int(m[1], 0)), text)
    if re.search(r'[^\sx0-9()<>=!+\-andotr]', text.replace('and', '').replace('or', '').replace('not', '')):
        raise Stop
    return text


def _close(body, index):
    """The line that closes the `{` at `index`; Stop when the braces never balance (the tree is not one to read)."""
    close = block_end(body, index)
    if close is None:
        raise Stop
    return close


def _parse(body, index, end):
    """Statements from index up to end (exclusive) as nodes; an `if` is ('if', condition, then, otherwise)."""
    nodes = []
    while index < end:
        node, index = _statement(body, index, end)
        if node is not None:
            nodes.append(node)
    return nodes


def _statement(body, index, end):
    """One statement at index as (node, next index); (None, next) for a blank line."""
    text = body[index].stripped
    if not text:
        return None, index + 1
    if text == '{':  # a bare block
        close = _close(body, index)
        return ('block', _parse(body, index + 1, close)), close + 1
    if re.match(r'if\s*\(', text):
        condition = text[text.index('(') + 1:text.rindex(')')]
        if index + 1 >= end or body[index + 1].stripped != '{':
            raise Stop
        close = _close(body, index + 1)
        then = _parse(body, index + 2, close)
        index = close + 1
        otherwise = []
        if index < end and body[index].stripped == 'else':
            if index + 1 < end and body[index + 1].stripped == '{':
                close = _close(body, index + 1)
                otherwise = _parse(body, index + 2, close)
                index = close + 1
            elif index + 1 < end and re.match(r'if\s*\(', body[index + 1].stripped):
                node, index = _statement(body, index + 1, end)
                otherwise = [node]
            else:
                raise Stop
        return ('if', condition, then, otherwise), index
    if (goto := re.fullmatch(r'goto\s+(\w+)\s*;', text)):
        return ('goto', goto[1]), index + 1
    if (label := LABEL.fullmatch(text)):
        return ('label', label[1]), index + 1
    return ('stmt', index), index + 1


def _run(nodes, x, name, state):
    """Walk the nodes for x; returns 'goto', 'label' or None while the walk continues."""
    for node in nodes:
        kind = node[0]
        if kind == 'if':
            try:
                taken = bool(eval(_python(node[1], name), {'__builtins__': {}}, {'x': x}))  # noqa: S307 (digits and operators only)
            except Stop:
                raise
            except Exception:
                raise Stop
            result = _run(node[2] if taken else node[3], x, name, state)
            if result:
                return result
        elif kind == 'block':
            result = _run(node[1], x, name, state)
            if result:
                return result
        elif kind in {'goto', 'label'}:
            return 'reach'
        elif kind == 'stmt':
            raise Stop  # a statement outside the label's block: the tree does more than choose
    return None


def _label_block(body, nodes, label):
    """Line indexes of the statements that follow the label in its block, or None."""
    for node in nodes:
        if node[0] in {'if'}:
            for branch in (node[2], node[3]):
                found = _label_block(body, branch, label)
                if found is not None:
                    return found
        elif node[0] == 'block':
            found = _label_block(body, node[1], label)
            if found is not None:
                return found
    flat = [n for n in nodes]
    for at, node in enumerate(flat):
        if node[0] == 'label' and node[1] == label:
            rest = flat[at + 1:]
            if rest and all(n[0] == 'stmt' for n in rest):
                return [n[1] for n in rest]
            return None
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for index, line in enumerate(body):
        if not re.match(r'if\s*\(', line.stripped) or index + 1 >= len(body) or body[index + 1].stripped != '{':
            continue
        try:
            end = block_end(body, index + 1)
            if end is None:
                continue
            nxt = end + 1
            if nxt < len(body) and body[nxt].stripped == 'else' and nxt + 1 < len(body) and body[nxt + 1].stripped == '{':
                end = block_end(body, nxt + 1)
                if end is None:
                    continue
            tree = _parse(body, index, end + 1)
            variable = re.search(r'\b([A-Za-z_]\w*)\b', CAST.sub(' ', re.sub(r'\binline_fn\w*', ' ', line.stripped[line.stripped.index('('):])))
            if not variable:
                continue
            label = next((n[1] for n in _walk(tree) if n[0] == 'label'), None)
            gotos = {n[1] for n in _walk(tree) if n[0] == 'goto'}
            if label is None or gotos - {label}:
                continue
            block = _label_block(body, tree, label)
            if not block:
                continue
            cases = []
            for x in DOMAIN:
                reached = _run_tree(tree, x, variable[1])
                if reached:
                    cases.append(x)
            if not cases or len(cases) > MAX_CASES or len(cases) == len(DOMAIN):
                continue
        except Stop:
            continue
        indent = line.indent
        inner = '\n'.join(indent + '    ' + body[at].stripped for at in block)
        labels = '\n'.join(f'{indent}  case {c}:' for c in cases)
        text = f'{indent}switch ({variable[1]})\n{indent}{{\n{labels}\n{inner}\n{indent}    break;\n{indent}}}\n'
        out.append(apply(source, [(body[index].start, body[end].end, text)]))
        if len(out) >= LIMIT:
            break
    return [(FAMILY, child) for child in dict.fromkeys(out)]


def _walk(nodes):
    for node in nodes:
        yield node
        if node[0] == 'if':
            yield from _walk(node[2])
            yield from _walk(node[3])
        elif node[0] == 'block':
            yield from _walk(node[1])


def _run_tree(tree, x, name):
    return _run(tree, x, name, {}) == 'reach'


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
