"""m2c's "Duplicate return node" `goto`, as the early return the source had.

When a test's failing branch returns the same value as the function's end, m2c writes the end as a label and jumps
to it:

    if (A) {
        if (B) {
            BODY;
            goto block_5;
        }
        /* Duplicate return node #6. Try simplifying control flow for better match */
        return -1;
    }
    block_5:
    return -1;

An N64 function was 91.3% so and exact as `if (A) { if (!B) { return -1; } BODY; } return -1;`. Offered when both
returns are the same and nothing else jumps to the label.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'duplicate_return_node'
FAMILIES = (FAMILY,)


def _opening(text, at):
    """The `{` of the block that contains position `at`."""
    depth = 0
    for i in range(at, -1, -1):
        if text[i] == '}':
            depth += 1
        elif text[i] == '{':
            if depth == 0:
                return i
            depth -= 1
    return None


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
    for jump in re.finditer(r'\bgoto\s+(\w+)\s*;', clean[opening:end]):
        label = jump[1]
        at = opening + jump.start()
        if len(re.findall(r'\bgoto\s+' + label + r'\s*;', clean[opening:end])) != 1:
            continue
        block = _opening(clean, at)
        if block is None or block == opening:
            continue
        block_end = close(clean, block, '{', '}')
        # the goto is the block's last statement, the block an `if (...)` with no else
        if clean[opening + jump.end():block_end - 1].strip():
            continue
        cond_close = len(clean[:block].rstrip())
        if clean[cond_close - 1] != ')':
            continue
        depth, cond_open = 0, None
        for i in range(cond_close - 1, -1, -1):
            depth += (clean[i] == ')') - (clean[i] == '(')
            if depth == 0:
                cond_open = i
                break
        keyword = re.search(r'\bif\s*$', clean[:cond_open]) if cond_open is not None else None
        if not keyword or re.match(r'\s*else\b', clean[block_end:]):
            continue
        after = re.compile(r'\s*(?:/\*[^\n]*?\*/\s*)?return\s+(?P<value>[^;]+);').match(clean, block_end)
        landing = re.compile(r'(?m)^[ \t]*' + label + r':[ \t]*\n[ \t]*return\s+(?P<value>[^;]+);').search(clean, opening, end)
        if not after or not landing or ' '.join(after['value'].split()) != ' '.join(landing['value'].split()):
            continue
        value = source[after.start('value'):after.end('value')].strip()
        cond = source[cond_open + 1:cond_close - 1].strip()
        inverse = negate(cond) or f'!({cond})'
        line = clean.rfind('\n', 0, keyword.start()) + 1
        ind = re.match(r'[ \t]*', clean[line:])[0]
        inner = source[block + 1:at].rstrip()
        inner = ''.join(l[4:] if l.startswith(ind + '    ') else l for l in inner.splitlines(keepends=True))
        replacement = f'if ({inverse}) {{\n{ind}    return {value};\n{ind}}}' + inner.rstrip() + '\n'
        text = source[:keyword.start()] + replacement + source[after.end():]
        cut = re.compile(r'(?m)^[ \t]*' + label + r':[ \t]*\n').search(text)
        if cut:
            text = text[:cut.start()] + text[cut.end():]
        result.append((FAMILY, text))
    return result[:2]
