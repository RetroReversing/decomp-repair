"""A result local that only ever holds literals on the way to `return V;`, written as the constant returns it stands for.

m2c keeps a function's result in one local and returns it from a shared tail:

    var_v0 = 0;
    if (a) {
        var_v0 = 0;
        if (b) { ...; return f(); }
        if (c) { g(); var_v0 = 1; }
        return var_v0;
    }
    return var_v0;

The game's source returned each constant where it is decided, `if (c) { g(); return 1; } return 0;`, and a function of
that shape (KMC GCC 2.7.2 `-O1 -g`, 120 -> 0 with the other repairs) had `move $v0,$zero` once per path where the draft
kept the result in a saved register and copied it at the end.

The rewrite follows the value of `V` through the function's `if`/`else` tree (no loops, `switch`, `goto` or braceless
`if`; V's address never taken). A `return V;` reached only with one literal value becomes `return K;`. An `if` without
an `else` that is followed by the block's final `return V;` and whose then-block leaves `V` at a literal that differs
from the one on the fall-through path gets its own `return K;` at the end of the then-block, and the final return then
becomes the fall-through literal. The assignments are left; the compiler drops them as dead.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'result_constant_returns'
FAMILIES = (FAMILY,)
_BANNED = re.compile(r'\b(?:for|while|do|switch|goto|case|default)\b|^\s*\w+\s*:(?!:)', re.M)
UNKNOWN = None


class _Bail(Exception):
    pass


def _parse(text, i, stop):
    """Statements of one block between `i` and `stop`: ('s', a, b) simple, ('if', a, b, cond, then, other)."""
    nodes = []
    while i < stop:
        while i < stop and text[i].isspace():
            i += 1
        if i >= stop:
            break
        hit = re.compile(r'if\s*\(').match(text, i)
        if hit:
            opening = hit.end() - 1
            past = close(text, opening, '(', ')')
            body = re.compile(r'\s*{').match(text, past) if past else None
            if not body:
                raise _Bail
            then_open = body.end() - 1
            then_end = close(text, then_open, '{', '}')
            if not then_end:
                raise _Bail
            then = _parse(text, then_open + 1, then_end - 1)
            other, end = None, then_end
            tail = re.compile(r'\s*else\b\s*').match(text, then_end)
            if tail:
                if text.startswith('if', tail.end()):
                    sub = _parse_one_if(text, tail.end(), stop)
                    other, end = [sub], sub[2]
                else:
                    other_open = tail.end()
                    if not text.startswith('{', other_open):
                        raise _Bail
                    other_end = close(text, other_open, '{', '}')
                    if not other_end:
                        raise _Bail
                    other, end = _parse(text, other_open + 1, other_end - 1), other_end
            nodes.append(('if', i, end, then, other, then_end - 1))
            i = end
            continue
        if text[i] == '{':
            end = close(text, i, '{', '}')
            if not end:
                raise _Bail
            nodes.append(('b', i, end, _parse(text, i + 1, end - 1)))
            i = end
            continue
        end = text.find(';', i, stop)
        if end < 0:
            raise _Bail
        nodes.append(('s', i, end + 1))
        i = end + 1
    return nodes


def _parse_one_if(text, i, stop):
    [node] = _parse_prefix(text, i, stop)
    return node


def _parse_prefix(text, i, stop):
    # The first statement only: parse the rest of the span and keep the first node.
    nodes = _parse(text, i, stop)
    return nodes[:1]


def _join(a, b):
    return a if a == b else UNKNOWN


class _Walk:
    def __init__(self, text, var, base):
        self.text, self.var, self.base = text, var, base
        self.edits = []
        self.write = re.compile(rf'\b{var}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\b{var}\s*(?:\+\+|--)|(?:\+\+|--)\s*{var}\b')
        self.literal = re.compile(rf'{var}\s*=\s*({NUMBER})\s*;')
        self.ret = re.compile(rf'return\s+{var}\s*;')

    def block(self, nodes, state):
        """Returns (state after, terminated)."""
        for at, node in enumerate(nodes):
            kind = node[0]
            if kind == 's':
                part = self.text[node[1]:node[2]]
                if self.ret.fullmatch(part.strip()):
                    if state is not UNKNOWN:
                        self.edits.append((node[1], node[2], f'return {state};'))
                    return state, True
                if re.match(r'\s*return\b', part):
                    return state, True
                lit = self.literal.fullmatch(part.strip())
                if lit:
                    state = int(lit[1].rstrip('uUlL'), 0)
                elif self.write.search(part):
                    state = UNKNOWN
            elif kind == 'b':
                state, done = self.block(node[3], state)
                if done:
                    return state, True
            else:
                _, _, end, then, other, then_close = node
                last = nodes[at + 1] if at + 1 < len(nodes) else None
                tail = (other is None and last and at + 2 == len(nodes) and last[0] == 's'
                        and self.ret.fullmatch(self.text[last[1]:last[2]].strip()))
                then_state, then_done = self.block(then, state)
                if tail and not then_done and then_state is not UNKNOWN and state is not UNKNOWN and then_state != state:
                    self.edits.append((then_close, then_close, f' return {then_state}; '))
                    self.edits.append((last[1], last[2], f'return {state};'))
                    return state, True
                other_state, other_done = self.block(other, state) if other is not None else (state, False)
                if then_done and other_done:
                    return state, True
                if then_done:
                    state = other_state
                elif other_done:
                    state = then_state
                else:
                    state = _join(then_state, other_state)
        return state, False


def variants(source, name):
    part = view(source, name)
    if not part or _BANNED.search(part.clean[part.opening:part.end]):
        return []
    text = part.clean
    try:
        nodes = _parse(text, part.opening + 1, close(text, part.opening, '{', '}') - 1)
    except _Bail:
        return []
    out = []
    for var in dict.fromkeys(re.findall(rf'\breturn\s+({IDENT})\s*;', text[part.opening:part.end])):
        if re.search(rf'&\s*{var}\b', text[part.opening:part.end]) or not re.search(rf'\b{var}\s*=\s*{NUMBER}\s*;', text[part.opening:part.end]):
            continue
        walk = _Walk(text, var, part.opening)
        walk.block(nodes, UNKNOWN)
        if walk.edits:
            out.append((FAMILY, edit(source, [(a, b, r) for a, b, r in walk.edits])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
