"""The `then` arm's constant written before the inverted test, as the default the other arm overwrites.

    if (c) {                      mode = 0x3E;
        mode = 0x3E;              if (!c) {
    } else {                          mode = 0x3D;
        mode = 0x3D;                  ...
        ...                       }
    }

The first lays out `beqz` to the else arm, the constant in a delay slot and a `j` over it; the second one `bnez` with
the constant in its slot and the other arm falling through (`default_else_repairs` moves a lone `else` default and
leaves this two-armed form). The arm is then reached by fall-through, so cse can fold a pointer set before a call into
its uses there (`*(u16 *) (p - 4)` becomes the symbol's address): the same source with an empty `do { } while (0);`
before the enclosing statement keeps the register. And a constant the enclosing block stores last (`flags = 0;`) is
offered at the block's top, where the compiler had it.

A 59-instruction N64 state update (KMC GCC 2.7.2, `-O1`) went 160 -> 0 with the three together; each pair of them
scores worse than the start, so they are one child. Labels `default_before_test`.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close, negate

FAMILIES = ('default_before_test',)
LITERAL = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'


def _enclosing(clean, opening, at):
    """The offset of the `{` of the innermost block of the function (its body at `opening`) that holds `at`."""
    stack = []
    for hit in re.finditer(r'[{}]', clean[opening:at]):
        if hit[0] == '{':
            stack.append(opening + hit.start())
        elif stack:
            stack.pop()
    return stack[-1] if stack else opening


def _head(clean, opening, block):
    """Where the statement that owns the `{` at `block` starts (`if (...) {`), or None for the function's body."""
    if block == opening:
        return None
    start = max(clean.rfind(mark, opening, block) for mark in ';{}') + 1
    hit = re.compile(r'\s*').match(clean, start)
    return hit.end() if re.match(r'if\s*\(', clean[hit.end():block]) else None


def _hoisted(source, clean, block, stop, at, indent):
    """The block's last statement `x = K;` moved to its top, for a local nothing else in the block names."""
    inner = clean[block + 1:stop - 1]
    last = re.search(rf'\n[ \t]*({IDENT})\s*=\s*{LITERAL}\s*;\s*$', inner)
    if not last or block + 1 + last.start() < at:
        return None
    local = last[1]
    if (len(re.findall(rf'(?<![\w.>]){local}\b', inner)) != 1 or re.search(rf'&\s*{local}\b(?!\s*&)', clean)
            or not re.search(rf'(?m)^[ \t]*(?:[\w ]+?[ \t*]+){local}\s*;|[(,][^(),;]*[ *]{local}\s*[,)]', clean)):
        return None
    statement = source[block + 1 + last.start():block + 1 + last.end()].strip()
    start, end = block + 1 + last.start(), block + 1 + last.end()
    closing = source[start:end]
    kept = source[:start] + closing[len(closing.rstrip()):] + source[end:]
    return kept[:block + 1] + f'\n{indent}{statement}' + kept[block + 1:]


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
    for hit in re.finditer(r'(?m)^(?P<indent>[ \t]*)if\s*\(', clean[:end]):
        if hit.start() < opening:
            continue
        paren = hit.end() - 1
        shut = close(clean, paren)
        arm = re.compile(rf'\s*{{\s*(?P<local>{IDENT})\s*=\s*(?P<value>{LITERAL})\s*;\s*}}\s*else\s*{{').match(clean, shut or end)
        if not shut or not arm:
            continue
        local = arm['local']
        brace = arm.end() - 1
        stop = close(clean, brace, '{', '}')
        if (not stop or not re.match(rf'\s*{local}\s*=(?!=)', clean[brace + 1:stop])
                or re.search(rf'(?<![\w.>]){local}\b|\+\+|--|(?<![=!<>])=(?!=)', clean[paren:shut])):
            continue
        indent = hit['indent']
        condition = source[paren + 1:shut - 1].strip()
        test = negate(condition) or f'!({condition})'
        start = hit.start()
        moved = (source[:start] + f'{indent}{local} = {arm["value"]};\n{indent}if ({test}) {{' + source[brace + 1:stop]
                 + source[stop:])
        result.append(moved)
        # (the offsets before `start` are unchanged, so the enclosing block is found on the original)
        block = _enclosing(clean, opening, start)
        head = _head(clean, opening, block)
        if head is None:
            continue
        text = _blank(moved)
        closing = close(text, block, '{', '}')
        top = _hoisted(moved, text, block, closing, start, indent) if closing else None
        line = moved.rfind('\n', 0, head) + 1
        margin = moved[line:head]
        for child in ([top] if top else []) + [moved]:
            if child == top:
                result.append(top)
            result.append(child[:line] + f'{margin}do {{ }} while (0);\n' + child[line:])
    return [('default_before_test', child) for child in dict.fromkeys(result)][:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
