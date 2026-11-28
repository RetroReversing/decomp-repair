"""m2c's jumps into other arms' tails, written as the paths they run, each in its own place.

Where two arms of an `if`/`else` finish the same way, the compiler's cross-jumping (after register allocation) keeps one
copy and sends the other arm into the middle of it. m2c reads that back as labels inside one arm and `goto`s from the
other, sometimes two labels in one block and a third on the function's end:

    if (a) { ... if (n >= 0x300) { goto block_9; } goto block_8; }
    else { ... if (n < 0x100) {
            block_8: ok = 0; flags(); goto block_11; }
        block_9: if (m >= 16) { full(); goto block_11; } }
    else { block_11: v = ok; }

`goto_shared_tail` declines this (the tails hold `goto`s of their own and the arms continue differently). Here every
jump is followed to where it ends, statement by statement, and the statements it would run are written where it stood:
`if (c) { goto A; } goto B;` becomes `if (c) { A's path } else { B's path }`, and what both ways go on to run anyway is
left where it is. The labels go. One child, the whole function.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 save-space check (141 instructions): from its repaired draft this
step alone went 1356 -> 215.

goto_paths_written_out
    Only for functions whose jumps all go forward and where no label or `goto` is inside a loop or `switch`. Declined
    when a path would have to be copied that declares something, when the result would grow past a few times the
    function's size, and when a path that must leave the function early has no `return` to end it.

goto_paths_literals
    The same paths, where a local only carried a literal to a store the jump shared (`v = 0xDAC; goto block_35; ...
    block_35: p->y = v;`): each store takes the literal and the local goes. The compiler merges the identical stores
    again itself. Offered as that, and with the written-out ladder's `!=` nests turned back into an `else if` chain
    (`inverted_guard_ladder`), the combination: measured on a 259-instruction N64 object reset (SN, `-O2 -mips3`),
    where the paths written out alone scored worse (3840 -> 4575), with literals 3960, and with the chain 2090.

A hypothesis like every family's; the judge decides.
"""
import re

from . import inverted_guard_ladder
from .csource import _blank, find
from .goto_structure_repairs import LOOPS, parse, walk
from .pattern_repairs import close

FAMILY = 'goto_paths_written_out'
LITERALS = 'goto_paths_literals'
FAMILIES = (FAMILY, LITERALS)

MAX_STATEMENTS = 400
_LITERAL = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_DECLARATION = re.compile(r'\s*(?!return\b|goto\b|else\b)[A-Za-z_]\w*(?:\s+|\s*\*+\s*)[A-Za-z_]\w*\s*[;=,\[]')


class _Decline(Exception):
    pass


class _Writer:
    def __init__(self, source, clean, function):
        self.source, self.clean = source, clean
        self.written = 0
        self.where = {}
        self.labels = {}
        self._index(function, ())

    def _index(self, stmts, follow_of):
        """Each statement list with the lists that run after it, and each label's place."""
        for i, s in enumerate(stmts):
            here = ((stmts, i), *follow_of)
            self.where[id(s)] = here
            if s.kind == 'label':
                if s.parts['name'] in self.labels:
                    raise _Decline
                self.labels[s.parts['name']] = s
            for key in ('then', 'other', 'body'):
                part = s.parts.get(key)
                if part:
                    self._index(part['stmts'], here)

    def path(self, stmts, follow, seen=()):
        """What runs from the head of `stmts`: its statements, then `follow`; a `goto` goes on at its label."""
        out = []
        for s in stmts:
            if s.kind == 'label':
                continue
            if s.kind == 'goto':
                return out + self.target(s, seen)
            out.append(s)
        return out + follow

    def after(self, s):
        """What runs after statement `s` falls through, out to the function's end."""
        follow = []
        for stmts, i in reversed(self.where[id(s)]):
            follow = self.path(stmts[i + 1:], follow)
        return follow

    def target(self, jump, seen=()):
        name = jump.parts['target']
        label = self.labels.get(name)
        if label is None or name in seen or label.start < jump.start:
            raise _Decline
        here = self.where[id(label)]
        follow = []
        for stmts, i in reversed(here[1:]):
            follow = self.path(stmts[i + 1:], follow, (*seen, name))
        stmts, i = here[0]
        return self.path(stmts[i + 1:], follow, (*seen, name))

    def text(self, s):
        return self.source[s.start:s.end].strip()

    def returns(self, nodes):
        return bool(nodes) and nodes[-1].kind == 'simple' and re.match(r'return\b', self.text(nodes[-1])) is not None

    @staticmethod
    def common(left, right):
        n = 0
        while n < min(len(left), len(right)) and left[-1 - n] is right[-1 - n]:
            n += 1
        return n

    @staticmethod
    def exits(stmts):
        return bool(stmts) and stmts[-1].kind == 'goto'

    def render(self, stmts, follow, depth):
        """The lines of a block that goes on to `follow` when it ends."""
        lines = []
        for i, s in enumerate(stmts):
            if s.kind == 'label':
                continue
            rest = self.path(stmts[i + 1:], follow)
            if s.kind == 'goto':
                if any(later.kind != 'label' for later in stmts[i + 1:]):
                    raise _Decline  # code after a jump that only another label reaches
                return lines + self.nodes(self.leaving(self.target(s), follow), follow, depth)
            siblings = [later for later in stmts[i + 1:] if later.kind != 'label']
            if s.kind == 'if' and not s.parts.get('other') and siblings and self.exits(s.parts['then']['stmts']):
                # The arm always jumps away, so what follows it in this block is its `else`.
                tail = self.shared_end(s, stmts[i + 1:], rest, follow)
                after = tail + follow
                lines += self.choice(s, self.render(s.parts['then']['stmts'], after, depth + 1),
                                     self.render(stmts[i + 1:len(stmts) - len(tail)], after, depth + 1), depth)
                return lines + self.render(tail, follow, depth)
            lines += self.one(s, rest, depth)
            if self.returns([s]):
                break  # what follows a `return` is only reached by a label, and is written at its jumps
        return lines

    def shared_end(self, s, siblings, rest, follow):
        """The last statements of the block that the jumping arm's path runs too: they stay after the `if`."""
        count = self.common(self.path(s.parts['then']['stmts'], rest), rest) - len(follow)
        count = min(max(count, 0), len(siblings) - 1)
        while count and any(a is not b for a, b in zip(siblings[-count:], rest[len(rest) - len(follow) - count:])):
            count -= 1
        return siblings[len(siblings) - count:]

    def leaving(self, path, follow):
        shared = self.common(path, follow)
        if shared == len(follow):
            return path[:len(path) - shared]
        if not self.returns(path):
            raise _Decline
        return path

    def nodes(self, nodes, follow, depth):
        """A path's statements written out, each going on to the rest of the path and then `follow`."""
        lines = []
        for k, s in enumerate(nodes):
            lines += self.one(s, nodes[k + 1:] + follow, depth)
        return lines

    def one(self, s, rest, depth):
        self.written += 1
        if self.written > MAX_STATEMENTS:
            raise _Decline
        pad = '    ' * depth
        if s.kind == 'if':
            then = self.render(s.parts['then']['stmts'], rest, depth + 1)
            other = s.parts.get('other')
            return self.choice(s, then, self.render(other['stmts'], rest, depth + 1) if other else [], depth)
        if s.kind == 'simple':
            if _DECLARATION.match(self.clean[s.start:s.end]):
                raise _Decline
            return [pad + self.text(s)]
        if s.kind == 'block':
            return [pad + '{', *self.render(s.parts['body']['stmts'], rest, depth + 1), pad + '}']
        if s.kind in LOOPS and not any(c.kind in ('goto', 'label') for c, _ in walk([s])):
            return [pad + self.text(s)]
        raise _Decline

    def choice(self, s, then, other, depth):
        pad = '    ' * depth
        condition = self.source[s.parts['cond'][0]:s.parts['cond'][1]].strip()
        lines = [f'{pad}if ({condition}) {{', *then]
        if other:
            if other[0].startswith(pad + '    if (') and _single_if(other, pad + '    '):
                shifted = [line[4:] for line in other]
                lines.append(f'{pad}}} else {shifted[0].lstrip()}')
                return lines + shifted[1:]
            lines += [f'{pad}}} else {{', *other]
        return lines + [pad + '}']


def _single_if(lines, pad):
    """Whether these lines are one `if` statement, so an `else` may hold it without braces."""
    heads = [line for line in lines if line.startswith(pad) and not line.startswith(pad + ' ')]
    return heads[-1] == pad + '}' and all(line == pad + '}' or line.startswith(pad + '} else') for line in heads[1:])


def _propagate(lines, local):
    """The lines with every `X = local;` given the literal `local` holds there and its assignments gone, or None.

    One statement or brace per line, as the writer emits them. An arm starts with the value held before its `if`; after
    blocks that assigned the local its value is unknown. Any other mention of the local declines."""
    assign = re.compile(rf'\s*{local}\s*=\s*({_LITERAL})\s*;')
    store = re.compile(rf'(?P<lhs>\s*[^=;{{}}]*[^=;{{}}<>!+\-*/%&|^\s]\s*=\s*){local}\s*;')
    value, dirty, outer, out, replaced = None, False, [], [], 0
    for line in lines:
        text = line.strip()
        if text.startswith('}') and outer:
            if text.endswith('{'):
                value = outer[-1][0]  # the next arm of the same `if`
                out.append(line)
                continue
            before, was = outer.pop()
            value, dirty = (None, True) if dirty else (before, was)
        found = assign.fullmatch(line)
        if found:
            value, dirty = found[1], True
        elif re.search(rf'\b{local}\b', line):
            use = store.fullmatch(line)
            if not use or re.search(rf'\b{local}\b', use['lhs']) or value is None:
                return None
            out.append(f"{use['lhs']}{value};")
            replaced += 1
        else:
            out.append(line)
        if text.endswith('{'):
            outer.append((value, dirty))
            dirty = False
    return out if replaced else None


def _repeats(body, local):
    """Whether a loop or `switch` mentions the local: its lines don't run once, top to bottom."""
    clean = _blank(body)
    for hit in re.finditer(r'\b(?:for|while|do|switch)\b', clean):
        brace = clean.find('{', hit.end())
        end = None if brace < 0 else close(clean, brace, '{', '}')
        stop = clean.find(';', end) if end and hit[0] == 'do' else end
        if re.search(rf'\b{local}\b', clean[hit.start():stop if stop and stop > 0 else len(clean)]):
            return True
    return False


def _literals(source, name):
    """The function with each literal-carrying local written into its stores, or None."""
    span = find(source, name)
    head, body, tail = source[:span[0]], source[span[0]:span[1]], source[span[1]:]
    opening = body.find('{')
    changed = False
    declared = re.findall(r'(?m)^[ \t]*(?:u8|s8|u16|s16|u32|s32|int|short|char)[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*$',
                          body[opening:])
    for local in declared:
        pattern = rf'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+{local}[ \t]*;[ \t]*\n'
        rest = re.sub(pattern, '', body, count=1)
        if not re.search(rf'\b{local}\s*=\s*{_LITERAL}\s*;', rest) or _repeats(rest, local):
            continue
        lines = _propagate(rest.split('\n'), local)
        if lines is not None:
            body, changed = '\n'.join(lines), True
    return head + body + tail if changed else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    if not re.search(r'\bgoto\b', body) or re.search(r'(?m)^\s*#|&&\s*[A-Za-z_]\w*\s*[;,)]\s*$|\b(?:asm|__asm__|setjmp)\b', body):
        return []
    try:
        function = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    for s, in_loop in walk(function):
        if in_loop and s.kind in ('goto', 'label'):
            return []
    # The declarations stay where they are; the statements after them are rewritten.
    first = 0
    while first < len(function) and function[first].kind == 'simple' and _DECLARATION.match(
            clean[function[first].start:function[first].end]):
        first += 1
    statements = function[first:]
    if not statements:
        return []
    try:
        writer = _Writer(source, clean, statements)
        lines = writer.render(statements, [], 1)
    except (_Decline, RecursionError):
        return []
    start = source.rfind('\n', 0, statements[0].start) + 1
    if source[start:statements[0].start].strip():
        start = statements[0].start
    out = source[:start] + '\n'.join(lines) + '\n' + source[end - 1:]
    if re.search(r'\bgoto\b', _blank(out)[opening:]):
        return []
    results = [(FAMILY, out)]
    literal = _literals(out, name)
    if literal:
        results += [(LITERALS, text) for _, text in inverted_guard_ladder.variants(literal, name)[:2]]
        results.append((LITERALS, literal))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
