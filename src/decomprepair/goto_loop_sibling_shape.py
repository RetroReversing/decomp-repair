"""A row loop kept as a labelled `goto` block, and its one commuted statement, written the way its siblings are, as one child.

`loop_storage_shapes` writes a counted loop as `__repair_rows: { B } if (C) goto __repair_rows;` so the loop pass leaves
it alone, and the Deep Permuter's operand-order rewrites then commute the one statement of a group of parallel ones
that kept the saved best's registers (`z = off[2] + (scale[2] * p[2]);` beside `c[0] = (p[0] * scale[0]) + off[0];`).
Each of the two is a step *back* from the game's C once the other is in place, and neither alone is visible:

- the loop as `do { B } while (C);` with the commuted statement kept scored 50 against the saved best's 35 (the goto
  loop's body is unweighted, the `do`'s loop depth doubles the weight of every reference in it);
- the commuted statement written as its siblings with the goto loop kept scored 60;
- both together scored 25, and with the weights of the code before the loop (`chain_weight_scope`) 0.

A 167-instruction KMC GCC 2.7.2 mesh-frame decoder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2
-fno-strength-reduce`): the third vertex coordinate's multiply took the other pair of `$f0`/`$f2` for the scale and the
converted word (`mul.s $f0,$f0,$f2` against the target's `mul.s $f2,$f2,$f0`) and its sum took the other register.
The cause, read from the 2.7.2 source and not instrumented in the compiler (a hypothesis): local-alloc.c ties the
product to the operand its insn names first, and the odd statement's operand order made the product share the scale's
quantity rather than the converted word's.

`variants` offers, in each block of statements: two or more parallel statements `P[0] = E0; P[1] = E1;` (every index a
literal, their right-hand sides the same expression once the index is blanked) and a later one whose right-hand side is
that expression with its indices advanced (`P[2] = E2;`, or a temporary `z = E2;` stored as `P[2] = z;`) up to the order
of `+` and `*` operands: that statement written like its siblings. When the block is a `__repair_*:` goto loop the
child also holds the `do`/`while` form (and the shape fix alone, and the loop alone, follow). The judge decides."""
import re

from .chain_weight_scope import statements_in
from .debris import _close, _jumps_out
from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_loop_sibling_shape'
FAMILIES = (FAMILY,)
LIMIT = 12
_TYPES = {'u8', 's8', 'u16', 's16', 'u32', 's32', 'f32', 'f64', 'int', 'short', 'char', 'unsigned', 'signed', 'float',
          'double', 'long'}
_TOKEN = re.compile(r'\s*(?:(?P<num>0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*)|(?P<id>[A-Za-z_]\w*)|(?P<op>->|<<|>>|[-+*/%()\[\].]))')


def _tokens(text):
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        hit = _TOKEN.match(text, pos)
        if not hit:
            return None
        out.append((hit.lastgroup, hit.group(hit.lastgroup)))
        pos = hit.end()
    return out


class _Parser:
    """The right-hand sides this family reads: names, literals, `.`, `->`, `[ ]`, casts, `+ - * / %`, `<< >>`, parentheses."""

    def __init__(self, tokens):
        self.tokens, self.pos = tokens, 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def take(self, value=None):
        kind, text = self.peek()
        if value is not None and text != value:
            raise ValueError(text)
        self.pos += 1
        return kind, text

    def expression(self):
        node = self.additive()
        if self.pos != len(self.tokens):
            raise ValueError('trailing')
        return node

    def binary(self, operators, below):
        node = below()
        while self.peek()[1] in operators and self.peek()[0] == 'op':
            op = self.take()[1]
            node = ('bin', op, node, below())
        return node

    def additive(self):
        return self.binary(('+', '-'), lambda: self.binary(('<<', '>>'), self.multiplicative))

    def multiplicative(self):
        return self.binary(('*', '/', '%'), self.unary)

    def unary(self):
        kind, text = self.peek()
        if text == '(' and self.pos + 2 < len(self.tokens) and self.tokens[self.pos + 1][1] in _TYPES:
            end = self.pos + 1
            while end < len(self.tokens) and self.tokens[end][1] != ')':
                if self.tokens[end][1] not in _TYPES and self.tokens[end][1] != '*':
                    raise ValueError('cast')
                end += 1
            cast = ' '.join(t for _, t in self.tokens[self.pos + 1:end])
            self.pos = end + 1
            return ('cast', cast, self.unary())
        if text in ('-', '*', '&') and kind == 'op':
            self.take()
            return ('un', text, self.unary())
        return self.postfix()

    def postfix(self):
        kind, text = self.take()
        if text == '(':
            node = self.additive()
            self.take(')')
            node = ('paren', node)
        elif kind in ('num', 'id'):
            node = (kind, text)
        else:
            raise ValueError(text)
        while self.peek()[1] in ('[', '.', '->') and self.peek()[0] == 'op':
            op = self.take()[1]
            if op == '[':
                node = ('index', node, self.additive())
                self.take(']')
            else:
                node = ('member', op, node, self.take()[1])
        if self.peek()[1] == '(':
            raise ValueError('call')
        return node


def _parse(text):
    tokens = _tokens(text.replace('#', '9999'))
    if not tokens:
        return None
    try:
        return _Parser(tokens).expression()
    except (ValueError, IndexError):
        return None


def _flatten(node, op):
    if node[0] == 'paren':
        node = node[1]
    if node[0] == 'bin' and node[1] == op:
        return _flatten(node[2], op) + _flatten(node[3], op)
    return [node]


def _canon(node):
    """The tree as text with `+` and `*` operands in a fixed order (their commutative chains flattened and sorted)."""
    kind = node[0]
    if kind == 'paren':
        return _canon(node[1])
    if kind == 'bin' and node[1] in ('+', '*'):
        return '(' + node[1].join(sorted(_canon(part) for part in _flatten(node, node[1]))) + ')'
    if kind == 'bin':
        return f'({_canon(node[2])}{node[1]}{_canon(node[3])})'
    if kind == 'cast':
        return f'({node[1]}){_canon(node[2])}'
    if kind == 'un':
        return node[1] + _canon(node[2])
    if kind == 'index':
        return f'{_canon(node[1])}[{_canon(node[2])}]'
    if kind == 'member':
        return f'{_canon(node[2])}{node[1]}{node[3]}'
    return node[1]


def _blank_indices(text, number):
    """`text` with every `[number]` written `[#]`, or None when it has none (nothing then says which index it is)."""
    out, count = re.subn(rf'\[\s*{number}\s*\]', '[#]', text)
    return out if count else None


def _shape_fixes(source, clean, start, limit):
    """[(edit span, new text, statement span)] for each statement written unlike its parallel siblings in this block."""
    statements = [(a, b) for a, b, simple in statements_in(clean, start, limit) if simple]
    parsed = []
    for a, b in statements:
        hit = re.fullmatch(r'\s*(?P<lhs>[^;=]+?)\s*=(?!=)\s*(?P<rhs>[^;]+);', clean[a:b])
        parsed.append((a, b, hit['lhs'].strip(), hit['rhs'].strip()) if hit else None)
    fixes = []
    for i, first in enumerate(parsed):
        if not first or i + 1 >= len(parsed) or not parsed[i + 1]:
            continue
        index = re.fullmatch(rf'(?P<base>{IDENT}(?:\.{IDENT}|->{IDENT})*)\s*\[\s*(?P<k>\d+)\s*\]', first[2])
        second = parsed[i + 1]
        again = re.fullmatch(r'(?P<base>[^\[]+)\[\s*(?P<k>\d+)\s*\]', second[2])
        if not index or not again or again['base'] != index['base'] or int(again['k']) != int(index['k']) + 1:
            continue
        template = _blank_indices(first[3], index['k'])
        if not template or _blank_indices(second[3], again['k']) != template:
            continue
        nxt = int(again['k']) + 1
        want = _canon(_parse(template)) if _parse(template) else None
        if want is None:
            continue
        for odd in parsed[i + 2:]:
            if not odd:
                continue
            blanked = _blank_indices(odd[3], nxt)
            if blanked is None or blanked == template or not _parse(blanked) or _canon(_parse(blanked)) != want:
                continue
            temp = re.fullmatch(IDENT, odd[2])
            stored = re.search(rf'(?m)^\s*{re.escape(index["base"])}\s*\[\s*{nxt}\s*\]\s*=\s*{re.escape(odd[2])}\s*;',
                               clean[odd[1]:limit]) if temp else None
            direct = not temp and odd[2].replace(' ', '') == f'{index["base"].replace(" ", "")}[{nxt}]'
            if not (stored or direct):
                continue
            new = template.replace('[#]', f'[{nxt}]')
            fixes.append((odd[0] + clean[odd[0]:odd[1]].index('=') + 1, odd[1] - 1, ' ' + new))
            break
    return fixes


def _goto_loops(clean):
    """[(start, end, body start, body end, condition)] for each `L: { B } if (C) goto L;` with a `__repair_*` label."""
    out = []
    for hit in re.finditer(r'(?P<label>__repair_\w+)\s*:\s*\{', clean):
        label = hit['label']
        if len(re.findall(rf'\bgoto\s+{label}\s*;', clean)) != 1:
            continue
        brace = hit.end() - 1
        end = _close(clean, brace)
        cond = re.match(r'\s*if\s*\(', clean[end:]) if end else None
        if not cond:
            continue
        open_ = end + cond.end() - 1
        close_ = _close(clean, open_, '(', ')')
        jump = re.match(rf'\s*(?:\{{\s*goto\s+{label}\s*;\s*\}}|goto\s+{label}\s*;)', clean[close_:]) if close_ else None
        if not jump or _jumps_out(clean[brace + 1:end - 1]):
            continue
        out.append((hit.start(), close_ + jump.end(), brace + 1, end - 1, clean[open_ + 1:close_ - 1].strip()))
    return out


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp|volatile)\b', part.body):
        return []
    clean = part.clean
    loops = _goto_loops(clean[:part.end])
    blocks = [(part.opening + 1, part.end - 1)] + [(a, b) for _, _, a, b, _ in loops]
    out = []
    for low, high in blocks:
        fixes = _shape_fixes(source, clean, low, high)
        if not fixes:
            continue
        edits = [(a, b, text) for a, b, text in fixes]
        loop = next((entry for entry in loops if (entry[2], entry[3]) == (low, high)), None)
        if loop:
            conversion = (loop[0], loop[1], 'do {' + source[loop[2]:loop[3]] + '} while (' + loop[4] + ');')
            inner = [(a, b, text) for a, b, text in edits]
            # the loop's text is replaced as a whole, so the fixes go into the new body first
            body = edit(source[loop[2]:loop[3]], [(a - loop[2], b - loop[2], text) for a, b, text in inner])
            out.append((FAMILY, edit(source, [(loop[0], loop[1], 'do {' + body + '} while (' + loop[4] + ');')])))
            out.append((FAMILY, edit(source, edits)))
            out.append((FAMILY, edit(source, [conversion])))
        else:
            out.append((FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry (registry.py)
