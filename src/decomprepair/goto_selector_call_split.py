"""A call several paths share behind a label, with the argument that differs held in a local, written out on each path.

m2c reads a cross-jumped call back as one call, a variable and `goto`s into the arm that holds it:

    if (two_player) {
        if (a) { v = 0xCA; goto shared; }
        if (b) { f(e, 0xC8, 0xCA); f(e, 0xC8, 0xCB); if (!c) { v = 0xCC; goto shared; } }
    } else { v = 0xC8; shared: f(e, 0xC8, v); }

As written, the selector is a pseudo of its own and the other arguments are loaded once, after the label. The target
loads every argument on each path and jumps to the one `jal` with the last one in its delay slot, which is what
cross-jumping leaves when the source made the call on every path:

    if (two_player) { if (a) { f(e, 0xC8, 0xCA); } else if (b) { ...; if (!c) { f(e, 0xC8, 0xCC); } } }
    else { f(e, 0xC8, 0xC8); }

(a 117-instruction N64 entity update, sn-n64-281 -O2: 1015 -> 25 with this one edit, the store run after its first
`if`/`else` then copied into both arms for 0). The compiler reading is a hypothesis from jump.c; the judge decides.

Where the labelled call ends a `void` function, its paths need no `else` chain: each `v = K; goto shared;` becomes the
call on K and a `return;` (a 242-instruction N64 text banner, sn-n64-281 -O2, printed at one of two columns this way:
the last edit of a draft's chain to 0).

For the `else` chain, the rewrite keeps the program: the call must be the last statement of the `else` of a braced `if`/`else` chain, every
`goto` must sit in an earlier arm of that chain where nothing but the jump's own path is left to run (a guard whose
body ends in the jump takes the statements after it as its `else`), and the local must be read by that call alone.
"""
import re

from .arm_block_support import IDENT, NUMBER, arm_chain, brace_pairs, indentation, line_start, statements
from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'goto_selector_call_split'
FAMILIES = (FAMILY,)

VALUE = rf'(?:-?{NUMBER}|{IDENT})'
LABELLED = re.compile(
    rf'(?<![\w.>])(?P<var>{IDENT})\s*=\s*(?P<value>{VALUE})\s*;\s*(?P<label>{IDENT})\s*:(?!:)\s*(?P<callee>{IDENT})\s*\(')
SET = re.compile(rf'(?P<var>{IDENT})\s*=\s*(?P<value>{VALUE})\s*;\Z')
GUARD = re.compile(r'if\s*\(')
STEP = '    '


class _Shape(Exception):
    pass


class _Rewrite:
    def __init__(self, source, clean, pairs, var, label, call):
        self.source, self.clean, self.pairs = source, clean, pairs
        self.var, self.label, self.call = var, label, call
        self.jump = re.compile(rf'\bgoto\s+{label}\s*;')
        self.used = []  # the places of `var` and the `goto`s this rewrite accounts for

    def jumps(self, lo, hi):
        return self.jump.search(self.clean, lo, hi) is not None

    def block(self, spans, indent):
        """The text of the statements `spans`, a block's tail on the way to the join, with each jump made a call."""
        out = []
        for index, (start, end) in enumerate(spans):
            if not self.jumps(start, end):
                found = SET.match(self.clean[start:end])
                if (found and found['var'] == self.var and index == len(spans) - 2
                        and self.jump.fullmatch(self.clean[spans[-1][0]:spans[-1][1]])):
                    self.used += [start + found.start('var'), spans[-1][0]]
                    out.append(indent + self.call(self.source[start + found.start('value'):start + found.end('value')]))
                    return out
                out.append(indent + self.source[start:end].strip())
                continue
            guard, blocks = self.guard(start, end)
            last = index == len(spans) - 1
            if len(blocks) == 1 and not last:
                # `if (c) { ..; v = K; goto L; } rest` -> `if (c) { ..; call(K); } else { rest }`
                inner = statements(self.clean, blocks[0][0] + 1, blocks[0][1])
                if len(inner) < 2 or not self.jump.fullmatch(self.clean[inner[-1][0]:inner[-1][1]]):
                    raise _Shape
                if any(self.jumps(*span) for span in inner[:-1]):
                    raise _Shape
                rest = spans[index + 1:]
                out.append(f'{indent}{guard} {{')
                out += self.block(inner, indent + STEP)
                chained = len(rest) == 1 and GUARD.match(self.clean, rest[0][0])
                other = self.block(rest, indent if chained else indent + STEP)
                if chained and self.jumps(*rest[0]):
                    out.append(f'{indent}}} else {other[0].lstrip()}')
                    out += other[1:]
                elif chained:
                    out += [f'{indent}}} else {other[0].lstrip()}']
                else:
                    out += [f'{indent}}} else {{', *other, f'{indent}}}']
                return out
            if not last:
                raise _Shape
            text = f'{indent}{guard} {{'
            out.append(text)
            out += self.block(statements(self.clean, blocks[0][0] + 1, blocks[0][1]), indent + STEP)
            if len(blocks) == 2:
                out.append(f'{indent}}} else {{')
                out += self.block(statements(self.clean, blocks[1][0] + 1, blocks[1][1]), indent + STEP)
            out.append(f'{indent}}}')
        return out

    def guard(self, start, end):
        """(`if (c)`, [its blocks]) of a braced `if`, with or without one braced `else`."""
        found = GUARD.match(self.clean, start)
        if not found:
            raise _Shape
        paren = close(self.clean, found.end() - 1, '(', ')')
        if not paren:
            raise _Shape
        at = paren + len(self.clean[paren:]) - len(self.clean[paren:].lstrip())
        if at not in self.pairs:
            raise _Shape
        blocks = [(at, self.pairs[at])]
        tail = self.clean[self.pairs[at] + 1:end]
        if tail.strip():
            other = re.match(r'\s*else\s*(?=\{)', tail)
            if not other:
                raise _Shape
            opening = self.pairs[at] + 1 + other.end()
            if self.pairs.get(opening) != end - 1:
                raise _Shape
            blocks.append((opening, end - 1))
        return self.source[start:paren], blocks


def _children(source, name):
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return
    by_close = {close_at: open_at for open_at, close_at in pairs.items()}
    for hit in LABELLED.finditer(clean, part.opening, part.end):
        var, label = hit['var'], hit['label']
        paren = close(clean, hit.end() - 1, '(', ')')
        stop = paren and re.match(r'\s*;\s*(?=\})', clean[paren:])
        if not stop:
            continue
        closing = paren + stop.end()
        chain = arm_chain(clean, by_close, closing)
        if not chain or not chain[-1][0] < hit.start():
            continue
        # the labelled statements are the `else` block's own, not nested deeper in it
        if any(chain[-1][0] < opening < hit.start() < end for opening, end in pairs.items()):
            continue
        arguments = clean[hit.end():paren - 1]
        uses = [m for m in re.finditer(rf'(?<![\w.>]){var}\b', arguments)]
        if len(uses) != 1 or not re.search(rf'(?:\A|,)\s*{var}\s*(?:,|\Z)', arguments):
            continue
        at = hit.end() + uses[0].start()
        head, tail = source[hit.start('callee'):at], source[at + len(var):paren] + ';'

        def call(value, head=head, tail=tail):
            return head + value + tail

        rewrite = _Rewrite(source, clean, pairs, var, label, call)
        edits = []
        try:
            for opening, end in chain[:-1]:
                if not rewrite.jumps(opening, end):
                    continue
                indent = indentation(source, end) if source[line_start(source, end):end].isspace() else ''
                body = rewrite.block(statements(clean, opening + 1, end), indent + STEP)
                edits.append((opening + 1, end, '\n' + '\n'.join(body) + '\n' + indent))
        except _Shape:
            continue
        jumps = [m.start() for m in rewrite.jump.finditer(clean, part.opening, part.end)]
        if not jumps or sorted(at_ for at_ in rewrite.used if clean.startswith('goto', at_)) != jumps:
            continue
        edits.append((hit.start(), paren + 1 + clean[paren:].index(';'), call(source[hit.start('value'):hit.end('value')])))
        # every other mention of the selector is its declaration
        known = {at_ for at_ in rewrite.used} | {hit.start('var'), at}
        others = [m for m in re.finditer(rf'(?<![\w.>]){var}\b', clean[:part.end])
                  if m.start() >= part.opening and m.start() not in known]
        if len(others) != 1:
            continue
        declared = re.compile(rf'(?m)^[ \t]*{IDENT}(?:\s+{IDENT})*\s+{var}\s*;[ \t]*\n').search(clean, part.opening)
        if not declared or not declared.start() <= others[0].start() < declared.end():
            continue
        edits.append((declared.start(), declared.end(), ''))
        child = source
        for start, end, text in sorted(edits, reverse=True):
            child = child[:start] + text + child[end:]
        yield child


def _returns(source, name):
    """The labelled call that ends a `void` function, made with each path's own value and a `return;`."""
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return
    clean = part.clean
    if not re.search(rf'\bvoid\s+{name}\s*\(', clean):
        return
    for hit in LABELLED.finditer(clean, part.opening, part.end):
        var, label = hit['var'], hit['label']
        paren = close(clean, hit.end() - 1, '(', ')')
        stop = paren and re.compile(r'\s*;').match(clean, paren)
        if not stop or clean[stop.end():part.end].strip(' \t\n}'):
            continue
        uses = list(re.finditer(rf'(?<![\w.>]){var}\b', clean[hit.end():paren - 1]))
        if len(uses) != 1 or not re.search(rf'(?:\A|,)\s*{var}\s*(?:,|\Z)', clean[hit.end():paren - 1]):
            continue
        at = hit.end() + uses[0].start()
        head, tail = source[hit.start('callee'):at], source[at + len(var):stop.end()]
        jumps = list(re.finditer(rf'\bgoto\s+{label}\s*;', clean[:part.end]))
        paths = list(re.finditer(rf'(?<=[;{{}}:])(?P<lead>\s*)(?<![\w.>]){var}\s*=\s*(?P<value>{VALUE})\s*;\s*'
                                 rf'goto\s+{label}\s*;', clean[:part.end]))
        if not jumps or len(jumps) != len(paths):
            continue
        declared = re.compile(rf'(?m)^[ \t]*{IDENT}(?:\s+{IDENT})*\s+{var}\s*;[ \t]*\n').search(clean, part.opening)
        mentions = list(re.finditer(rf'(?<![\w.>]){var}\b', clean[part.opening:part.end]))
        if not declared or len(mentions) != len(paths) + 3:
            continue
        edits = [(declared.start(), declared.end(), ''), (hit.start(), stop.end(), head + hit['value'] + tail)]
        for path in paths:
            start = path.end('lead')
            indent = source[line_start(source, start):start]
            indent = indent if indent.isspace() else ''
            edits.append((start, path.end(), f'{head}{path["value"]}{tail}\n{indent}return;'))
        child = source
        for start, end, text in sorted(edits, reverse=True):
            child = child[:start] + text + child[end:]
        yield child


def variants(source, name):
    children = [*_children(source, name), *_returns(source, name)]
    return [(FAMILY, child) for child in dict.fromkeys(children) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 97}
