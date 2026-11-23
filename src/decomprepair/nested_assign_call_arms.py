"""A call after a tree of `if`s that set one of its arguments, made in each leaf of the tree with the literal in place.

m2c reads a three-way pick of a constant argument as a variable and one call after the tree:

    if (a < b) { v = 0x17; } else { v = 0x1A; if (!(c < a)) { v = 0x1B; } }
    f(p, v, 0x1B);

`call_into_arms` writes a call into each arm of a chain whose arms *end* by setting the variable. This shape sets it at the
head of an arm and overrides it in a nested `if`, so no arm ends in the assignment and the family never fires. The game
called in each leaf, and cross-jumping then joins the calls, which is where its argument registers and its delay slots
come from. In a 443-instruction KMC gcc 2.7.2 display-state updater (`-G0 -mips3 -mgp32 -mfp32 -O2`) the three leaves are the
rows that follow (580 -> 0 with the other families of its match; the draft's single call was 15 rows):

    if (a < b) { f(p, 0x17, 0x1B); } else if (c < a) { f(p, 0x1A, 0x1B); } else { f(p, 0x1B, 0x1B); }

The tree is read as `V = literal;` statements and `if (cond) { ... } else { ... }` blocks (an `else if` too); every path
must set `V`, `V` is read by nothing but the call that follows the tree and is not mentioned afterwards. Both polarities of
a `!( ... )` condition are offered, as written and with its two arms swapped. At most 8 leaves. A candidate for the exact
judge, never a verdict.
"""
import re

from .arm_block_support import statements
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'nested_assign_call_arms'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
MAX_LEAVES = 8


class _Parser:
    def __init__(self, source, clean, var):
        self.source, self.clean = source, clean
        self.assign = re.compile(rf'{re.escape(var)}\s*=(?!=)\s*(?P<value>{NUM})\s*;')

    def skip(self, pos):
        while pos < len(self.clean) and self.clean[pos].isspace():
            pos += 1
        return pos

    def block(self, lo, hi):
        nodes, pos = [], self.skip(lo)
        while pos < hi:
            hit = self.assign.match(self.clean, pos)
            if hit:
                nodes.append(('set', hit['value']))
                pos = self.skip(hit.end())
                continue
            if not re.match(r'if\s*\(', self.clean[pos:pos + 12]):
                return None
            node = self.branch(pos)
            if not node:
                return None
            nodes.append(node[0])
            pos = self.skip(node[1])
        return nodes

    def branch(self, pos):
        """(('if', cond, then, else), end) for the `if` at `pos`, or None."""
        clean = self.clean
        left = clean.index('(', pos)
        right = close(clean, left)
        if not right:
            return None
        cond = self.source[left + 1:right - 1].strip()
        at = self.skip(right)
        if clean[at:at + 1] != '{':
            return None
        then_end = close(clean, at, '{', '}')
        then = self.block(at + 1, then_end - 1) if then_end else None
        if then is None:
            return None
        end, other = then_end, []
        after = self.skip(then_end)
        if re.match(r'else\b', clean[after:after + 5]):
            at = self.skip(after + 4)
            if clean[at:at + 1] == '{':
                other_end = close(clean, at, '{', '}')
                other = self.block(at + 1, other_end - 1) if other_end else None
                end = other_end
            elif re.match(r'if\s*\(', clean[at:at + 12]):
                inner = self.branch(at)
                other, end = ([inner[0]], inner[1]) if inner else (None, None)
            else:
                return None
            if other is None:
                return None
        return ('if', cond, then, other), end


def _tree(sequence, value):
    """The decision tree of running `sequence` (nodes) from `value`: ('call', literal) or ('if', cond, then, else)."""
    for index, node in enumerate(sequence):
        if node[0] == 'set':
            value = node[1]
            continue
        rest = sequence[index + 1:]
        then = _tree(node[2] + rest, value)
        other = _tree(node[3] + rest, value)
        return None if then is None or other is None else ('if', node[1], then, other)
    return None if value is None else ('call', value)


def _leaves(tree):
    return 1 if tree[0] == 'call' else _leaves(tree[2]) + _leaves(tree[3])


def _flip(tree):
    """The same tree with `if (!(x)) { A } else { B }` as `if (x) { B } else { A }` wherever the condition has that form."""
    if tree[0] == 'call':
        return tree
    cond, then, other = tree[1], _flip(tree[2]), _flip(tree[3])
    hit = re.fullmatch(r'!\s*\((.*)\)', cond, re.S)
    if hit and close(cond, cond.index('(')) == len(cond):
        return ('if', hit[1].strip(), other, then)
    return ('if', cond, then, other)


def _render(tree, call, indent, step):
    if tree[0] == 'call':
        return f'{indent}{call(tree[1])}\n'
    text = f'{indent}if ({tree[1]})\n{indent}{{\n{_render(tree[2], call, indent + step, step)}{indent}}}\n'
    other = tree[3]
    if other[0] == 'call':
        return text + f'{indent}else\n{indent}{{\n{_render(other, call, indent + step, step)}{indent}}}\n'
    if other[0] == 'if' and _chain(other):
        return text + f'{indent}else\n' + _render(other, call, indent, step)
    return text + f'{indent}else\n{indent}{{\n{_render(other, call, indent + step, step)}{indent}}}\n'


def _chain(tree):
    return tree[0] == 'if'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    out = []
    for block_open in [opening] + [m.start() for m in re.finditer(r'\{', clean[opening + 1:end - 1])]:
        block_open = block_open if block_open == opening else opening + 1 + block_open
        block_close = close(clean, block_open, '{', '}')
        if not block_close:
            continue
        spans = statements(clean, block_open + 1, block_close - 1)
        for (a, b), (c, d) in zip(spans, spans[1:]):
            if not re.match(r'if\s*\(', clean[a:a + 12]):
                continue
            call = re.fullmatch(rf'(?P<head>{IDENT}\s*\()(?P<args>[^;{{}}]*)\)\s*;', clean[c:d].strip())
            if not call:
                continue
            for var in dict.fromkeys(re.findall(rf'(?<![\w.>&])({IDENT})(?!\s*\()', call['args'])):
                outside = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[opening + 1:end - 1])
                           if not a <= opening + 1 + m.start() < d
                           and not re.match(rf'[ \t]*[\w ]+[ \t]+\**[ \t]*{re.escape(var)}[ \t]*;', clean[clean.rfind('\n', 0, opening + 1 + m.start()) + 1:])]
                if outside:
                    continue  # set before the tree or read after it
                parser = _Parser(source, clean, var)
                node = parser.branch(a)
                if not node or node[1] != b:
                    continue
                tree = _tree([node[0]], None)
                if not tree or _leaves(tree) > MAX_LEAVES or var not in clean[a:b]:
                    continue
                text_call = source[c:d].strip()

                def make(value, var=var, text_call=text_call):
                    return re.sub(rf'(?<![\w.>&]){re.escape(var)}\b(?!\s*\()', value, text_call)

                indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, a) + 1:a])[0]
                step = '    ' if '\n    ' in source or '\n\t' not in source else '\t'
                for shape in dict.fromkeys([tree, _flip(tree)]):
                    body = _render(shape, make, indent, step).rstrip('\n').lstrip()
                    text = source[:a] + body + source[d:]
                    if text != source and (FAMILY, text) not in out:
                        out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
