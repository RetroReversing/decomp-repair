"""A loop body that ends in `if (A || B) { ... }`, written as the two tests that skip it.

For two plain comparisons the compiler folds `A || B` into one branch on a bitwise combination (`xori`, `sltu`, `or`,
then one `beqz`), where the game's code tested them one after the other: a branch for each, with the second test
only run when the first did not decide (`lbu` of the flag, `beqz` past the check, `beq` on the counter, the body after
them). In a 534-instruction panel builder the second form was the target's; the loop's slot loop went 15436 -> 14651
with that edit alone (the combined test also moves the flag's load above the body's first store, which the two
branches do not). Why the first form is folded is a hypothesis (fold-const's TRUTH_ORIF_EXPR -> TRUTH_OR_EXPR for
operands without side effects), not read in the compiler's source here.

The same fold hides in a guard that skips the rest of the body: `if (A || B) { continue; }` is one combined branch where
the game wrote `if (A) { continue; }` and `if (B) { continue; }` (a 534-instruction panel builder's inner loop,
10386 -> 9321 with it); `variants` offers that split too, for each such `continue` whose two sides are plain comparisons.

`variants` rewrites, in each `for`/`while` body, a last statement `if (A || B) { BODY }` (no `else`, `A` and `B` plain
comparisons of names, constants and field reads, no assignment, call or `++`) into

    if (!A) { if (!B) { continue; } }
    { BODY }

with `!A` the comparison's opposite (`==` and `!=`, `<` and `>=`, `>` and `<=`). The body must not use `break` or
`continue` of its own that would change meaning (it would not, but a `continue` there is left to the reader: bodies
holding one are skipped) and nothing may follow the `if` in the loop body. One child per loop, at most 3."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'or_guard_continue'
FAMILIES = (FAMILY,)
LIMIT = 3
OPPOSITE = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}
COMPARE = re.compile(r'^\s*\(?\s*([^=!<>()]+?(?:\([^()]*\))?)\s*(==|!=|<=|>=|<|>)\s*([^=!<>()]+?)\s*\)?\s*$')
LOOP = re.compile(r'\b(?:for|while)\s*\(')


def _flip(atom):
    hit = COMPARE.match(atom)
    if not hit or re.search(r'\+\+|--|[^=!<>]=[^=]|\w\s*\(', atom):
        return None
    return f'{hit[1].strip()} {OPPOSITE[hit[2]]} {hit[3].strip()}'


def _split_or(cond):
    parts, depth, last, at = [], 0, 0, 0
    while at < len(cond):
        char = cond[at]
        depth += (char == '(') - (char == ')')
        if depth == 0 and cond.startswith('||', at):
            parts.append(cond[last:at])
            last = at = at + 2
            continue
        at += 1
    parts.append(cond[last:])
    return parts


def _blocks(text, pattern):
    """`text` without the `{...}` blocks that follow `pattern` (a nested loop or switch owns its own jumps)."""
    while True:
        hit = re.search(pattern, text)
        if not hit:
            return text
        end = close(text, text.index('{', hit.end() - 1), '{', '}')
        if not end:
            return text[:hit.start()]
        text = text[:hit.start()] + ' ' * (end - hit.start()) + text[end:]


def _jumps(body):
    """True when the body jumps out of itself in a way the guard would change: a `goto`, a `continue` or a `break`
    that is not inside a nested loop (or, for `break`, a nested switch)."""
    plain = _blocks(body, r'\b(?:for|while)\s*\([^{};]*\)\s*\{')
    plain = _blocks(plain, r'\bdo\s*\{')
    if re.search(r'\b(?:continue|goto)\b', plain):
        return True
    return bool(re.search(r'\bbreak\b', _blocks(plain, r'\bswitch\s*\([^{};]*\)\s*\{')))


SKIP = re.compile(r'\bif\s*\(')


def _skips(source, clean, span):
    """`if (A || B) { continue; }` as `if (A) { continue; }` and `if (B) { continue; }`: one child for all of them."""
    edits = []
    for hit in SKIP.finditer(clean, span[0], span[1]):
        cond_open = hit.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close:
            continue
        tail = re.match(r'\s*(?:\{\s*continue\s*;\s*\}|continue\s*;)', clean[cond_close:span[1]])
        if not tail or re.match(r'\s*else\b', clean[cond_close + tail.end():span[1]]):
            continue
        parts = _split_or(clean[cond_open + 1:cond_close - 1])
        if len(parts) < 2 or any(_flip(part) is None for part in parts):
            continue
        line = source.rfind('\n', 0, hit.start()) + 1
        indent = re.match(r'[ \t]*', source[line:hit.start()])[0]
        if source[line:hit.start()].strip():
            continue  # (not the first thing on its line)
        text = ('\n' + indent).join(f'if ({part.strip()})\n{indent}{{\n{indent}    continue;\n{indent}}}' for part in parts)
        edits.append((hit.start(), cond_close + tail.end(), text))
    if not edits:
        return []
    out = source
    for a, b, text in sorted(edits, reverse=True):
        out = out[:a] + text + out[b:]
    return [out]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = _skips(source, clean, span)
    for loop in LOOP.finditer(clean, span[0], span[1]):
        head_close = close(clean, loop.end() - 1)
        if not head_close:
            continue
        body_open = clean.find('{', head_close)
        if body_open < 0 or clean[head_close:body_open].strip():
            continue
        body_close = close(clean, body_open, '{', '}')
        if not body_close:
            continue
        # the last statement of the body: the final `if (...) { ... }` before the closing brace
        stop = body_close - 1
        while stop > body_open and clean[stop - 1] in ' \t\n':
            stop -= 1
        if clean[stop - 1:stop] != '}':
            continue
        depth, start = 0, None
        for at in range(stop - 1, body_open, -1):
            depth += (clean[at] == '}') - (clean[at] == '{')
            if depth == 0:
                start = at
                break
        if start is None:
            continue
        # the `if (` whose condition closes right before this block
        cond_close = start
        while cond_close > body_open and clean[cond_close - 1] in ' \t\n':
            cond_close -= 1
        if clean[cond_close - 1:cond_close] != ')':
            continue
        depth, cond_open = 0, None
        for at in range(cond_close - 1, body_open, -1):
            depth += (clean[at] == ')') - (clean[at] == '(')
            if depth == 0:
                cond_open = at
                break
        if cond_open is None or not re.search(r'\bif\s*$', clean[body_open:cond_open]):
            continue
        if_start = cond_open - len(re.search(r'\bif\s*$', clean[body_open:cond_open])[0])
        if re.search(r'\belse\s*$', clean[body_open + 1:if_start]):
            continue  # the `if` closes an `else`: it is not the loop's last independent statement
        parts = _split_or(clean[cond_open + 1:cond_close - 1])
        if len(parts) != 2:
            continue
        first, second = _flip(parts[0]), _flip(parts[1])
        if not first or not second:
            continue
        inner = source[start:stop]
        if _jumps(clean[start:stop]):
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, if_start) + 1:if_start])[0]
        text = (f'if ({first})\n{indent}{{\n{indent}    if ({second})\n{indent}    {{\n{indent}        continue;\n'
                f'{indent}    }}\n{indent}}}\n{indent}{inner}')
        out.append(source[:if_start] + text + source[stop:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 64}
