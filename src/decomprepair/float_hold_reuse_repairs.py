"""A float expression held in a local the function reuses, and a single-use float temporary written inline.

GCC 2.x's local allocator (local-alloc.c) gives a pseudo that is born and dies in one basic block a register of
its own, lowest free one first, and ties the result of an arithmetic insn to the operand that dies there. A float
local that the function assigns in more than one place is referenced from two blocks, so it is left to the global
allocator and takes part in neither. Which of the two a value is therefore decides which FPR its neighbours get:
the product of a held factor lands in the register of the constant it multiplies, the conversion's result in the
next one, and a chain of three or four stores is either all the target's or all off by one register.

A KMC GCC 2.7.2 function (an N64 audio mixer's pan/volume stage, four `s16` outputs from table interpolations)
stood at 85 with every one of its 17 mismatched rows a float register operand. What closed it was a set of edits
that were each no better, or worse, alone:

    *d = (s32) (((1.0f - p) * A[i] + p * B[i]) * K);          q = (1.0f - p) * A[i] + p * B[i]; *d = (s32) (q * K);
    *a = (s32) (r * ((1.0f - p) * T[i] + p * T[i + 1]) * S);  t = (1.0f - p) * T[i] + p * T[i + 1]; *a = (s32) (r * t * S);
    v = q * t; *c = (s32) (v * K);                             *c = (s32) (q * t * K);
    v = r * (...) * S; *b = (s32) v;                           t = (...); *b = (s32) (r * t * S);

85 -> 65 (the first), 60 (the second), 585 (the third, with the fourth), 0 (all of them; `v` is a local assigned in
three arms, which is why it, too, must not be the one carrying a single-use value). The landscape between 85 and 0
is not monotone one edit at a time, so this offers the edits as bundles, smallest first.

Two kinds of edit, combined:
 - *hold*: a parenthesised float sum that is a factor of a product (`... * (a * b + c * d) ...`) is assigned to a
   float local first, `L = a * b + c * d;`, and the factor becomes `L`. `L` is any declared float local the statement
   does not mention that is dead there: no later mention reads it before the function assigns it again in the same
   or an enclosing block (so every path that goes on from the statement writes it first). Up to two locals a site.
 - *inline*: `V = expr;` directly followed by a statement that reads `V` once, with `V` dead after it, becomes that
   statement with `(expr)` in place of `V`.

The meaning is unchanged: nothing here reorders float arithmetic (a held factor and an inlined temporary keep their
operands and operators), and a group holding a literal without the `f` suffix (a double) or a call is left alone.
Functions with loops, `goto` or `switch` are left alone: the liveness reading is straight-line, branch-and-join only.
"""
import itertools
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_hold_reuse'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
# how many locals a site may be held in, how many sites and inlines one bundle may change, and how many bundles
OPTIONS = 2
MAX_SITES = 4
MAX_INLINES = 4
LIMIT = 300

_FLOAT_DECLARATION = re.compile(r'(?:^|(?<=[;{}]))\s*(?:f32|float)\s+([^;(){}*]+);')
_KEYWORD = re.compile(r'(?:if|else|while|for|do|return|switch|case|default|break|continue|goto|typedef)\b')
_DECLARATION = re.compile(r'(?:volatile\s+|register\s+|const\s+)*(?:unsigned\s+|signed\s+)?'
                          r'(?:f32|f64|float|double|s8|u8|s16|u16|s32|u32|s64|u64|int|long|short|char|void)\b')
_FLOW = re.compile(r'\b(?:for|while|do|goto|switch|asm|__asm__)\b')
_CALL = re.compile(IDENT + r'\s*\(')
_ALLOWED = re.compile(r'[\w\s.+\-*/()\[\]]+')
_SUFFIXED = re.compile(r'(?<![\w.])(?:\d+\.\d*|\.\d+|\d+)[fF]\b')
_DOUBLE = re.compile(r'(?<![\w.])(?:\d+\.\d*|\.\d+)(?![\dfFeE])|(?<![\w.])\d+[eE][+-]?\d+(?![fF])')


def _binary(value):
    """The top-level binary operators of an expression, as (position, operator)."""
    depth, found = 0, []
    for position, char in enumerate(value):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and char in '+-*/':
            before = value[:position].rstrip()
            if before and (before[-1] in ')]' or before[-1].isalnum() or before[-1] in '_.'):
                if not (before[-1] in 'eE' and re.search(r'\d[eE]$', before)):
                    found.append((position, char))
    return found


def _word(name):
    return re.compile(r'(?<![\w.>])' + re.escape(name) + r'\b')


class _Node:
    """One statement, or one `if` with its two arms, in the order the function runs them."""

    def __init__(self, start, stop, braced, kind='stmt'):
        self.start, self.stop, self.braced, self.kind = start, stop, braced, kind
        self.items = None
        self.then = self.otherwise = None
        self.condition = (0, 0)


class _Function:
    """The function's statements and `if` trees, read from the blanked source (no loops, switches or gotos)."""

    def __init__(self, source, name):
        self.ok = False
        span = find(source, name)
        if not span:
            return
        clean = _blank(source)
        opening = clean.find('{', span[0], span[1])
        end = close(clean, opening, '{', '}') if opening >= 0 else None
        if not end:
            return
        self.source, self.clean, self.opening, self.end = source, clean, opening, end
        if _FLOW.search(clean[opening:end]):
            return
        self.floats = []
        for hit in _FLOAT_DECLARATION.finditer(clean, opening, end):
            for part in hit[1].split(','):
                local = re.match(r'\s*(' + IDENT + r')\s*(?:=[^,]*)?$', part)
                if local and local[1] not in self.floats:
                    self.floats.append(local[1])
        self.statements = []  # (start, stop, node) of the plain statements, in text order
        self.owner = {}  # id(list of nodes) -> (the list it is an arm or body of, its position there)
        self.body = []
        self.owner[id(self.body)] = None
        try:
            self._block(self.body, opening + 1, end - 1, True)
        except _Unread:
            return
        self.ok = bool(self.floats and self.statements)

    def _skip(self, position):
        while position < self.end and self.clean[position].isspace():
            position += 1
        return position

    def _block(self, items, position, stop, braced):
        position = self._skip(position)
        while position < stop:
            position = self._item(items, position, stop, braced)
            position = self._skip(position)

    def _item(self, items, position, stop, braced):
        clean = self.clean
        if clean[position] == '{':
            closing = close(clean, position, '{', '}')
            if not closing:
                raise _Unread
            self._block(items, position + 1, closing - 1, True)
            return closing
        if clean.startswith(';', position):
            return position + 1
        word = re.match(r'(?:if|else|return|case|default|break|continue|typedef)\b|' + IDENT, clean[position:])
        if word and word[0] == 'if':
            node = _Node(position, position, braced, 'if')
            node.items = items
            opening = clean.find('(', position)
            closing = close(clean, opening)
            if not closing:
                raise _Unread
            node.condition = (opening, closing)
            node.then = []
            self.owner[id(node.then)] = (items, len(items))
            after = self._arm(node.then, closing, stop)
            probe = self._skip(after)
            if re.match(r'else\b', clean[probe:probe + 5]):
                node.otherwise = []
                self.owner[id(node.otherwise)] = (items, len(items))
                after = self._arm(node.otherwise, probe + 4, stop)
            node.stop = after
            items.append(node)
            return after
        depth, cursor = 0, position
        while cursor < stop:
            char = clean[cursor]
            depth += (char == '(') - (char == ')')
            if depth == 0 and char == ';':
                break
            if depth == 0 and char in '{}':
                raise _Unread
            cursor += 1
        if cursor >= stop:
            raise _Unread
        node = _Node(position, cursor + 1, braced)
        node.items = items
        text = clean[position:cursor + 1]
        node.kind = 'plain' if (_KEYWORD.match(text) or _DECLARATION.match(text)) else 'stmt'
        if node.kind == 'stmt':
            self.statements.append((position, cursor + 1, node))
        items.append(node)
        return cursor + 1

    def _arm(self, items, position, stop):
        position = self._skip(position)
        if self.clean[position] == '{':
            closing = close(self.clean, position, '{', '}')
            if not closing:
                raise _Unread
            self._block(items, position + 1, closing - 1, True)
            return closing
        return self._item(items, position, stop, False)

    def _state(self, local, items):
        """'read' when some path through `items` may read `local` before writing it, 'killed' when every path
        writes it first, else 'untouched'."""
        word = _word(local)
        for node in items:
            if node.kind == 'if':
                if word.search(self.clean, *node.condition):
                    return 'read'
                arms = [self._state(local, node.then), self._state(local, node.otherwise or [])]
                if 'read' in arms:
                    return 'read'
                if arms == ['killed', 'killed']:
                    return 'killed'
                continue
            text = self.clean[node.start:node.stop]
            if not word.search(text):
                continue
            assigned = re.match(r'\s*' + re.escape(local) + r'\s*=(?!=)\s*([^;]*);', text)
            if node.kind == 'stmt' and assigned and not word.search(assigned[1]):
                return 'killed'
            return 'read'
        return 'untouched'

    def dead_after(self, local, node):
        """Whether no path that goes on from the statement `node` reads `local` before writing it."""
        while True:
            items = node.items
            state = self._state(local, items[items.index(node) + 1:])
            if state != 'untouched':
                return state == 'killed'
            link = self.owner.get(id(items))
            if link is None:
                return True
            node = link[0][link[1]]


class _Unread(Exception):
    """The function has a shape this family does not read."""


def _group_sites(function, index):
    """The outermost parenthesised float sums that are factors of a product in statement `index`: (open, close)."""
    start, stop, _ = function.statements[index]
    text = function.clean[start:stop]
    found = []
    for opening in (m.start() for m in re.finditer(r'\(', text)):
        if found and opening < found[-1][1]:
            continue  # inside the last group taken: outermost only
        closing = close(text, opening)
        if not closing:
            continue
        inner = text[opening + 1:closing - 1]
        operators = _binary(inner)
        if not any(op in '+-' for _, op in operators) or not _ALLOWED.fullmatch(inner) or _CALL.search(inner):
            continue
        floating = _SUFFIXED.search(inner) or any(_word(local).search(inner) for local in function.floats)
        if '*' not in inner or _DOUBLE.search(inner) or not floating:
            continue
        before, after = text[:opening].rstrip(), text[closing:].lstrip()
        product = after[:1] == '*' and after[:2] != '**'
        product = product or (before[-1:] == '*' and re.search(r'[\w)\]]\s*\*$', before) is not None)
        if product and not (before[-1:].isalnum() or before[-1:] in ')_'):
            found.append((start + opening, start + closing))
    return found


def _holds(function):
    """[(statement index, (open, close), [locals that may carry the group])] for every site that has one."""
    sites = []
    for index, (start, stop, node) in enumerate(function.statements):
        mentioned = function.clean[start:stop]
        if not node.braced:
            continue
        for group in _group_sites(function, index):
            carriers = [local for local in function.floats
                        if not _word(local).search(mentioned) and function.dead_after(local, node)]
            if carriers:
                sites.append((index, group, carriers[:OPTIONS]))
    return sites[:MAX_SITES]


def _inlines(function):
    """[(first index, second index, local)] where `V = expr;` is followed by the one statement that reads V."""
    found = []
    for index in range(len(function.statements) - 1):
        (a0, a1, first), (b0, b1, second) = function.statements[index], function.statements[index + 1]
        if first.items is not second.items or not first.braced or first.items.index(first) + 1 != first.items.index(second):
            continue
        assigned = re.fullmatch(r'(' + IDENT + r')\s*=(?!=)\s*([^;]*);', function.clean[a0:a1])
        if not assigned or assigned[1] not in function.floats:
            continue
        local, value = assigned[1], assigned[2]
        if (_word(local).search(value) or not _ALLOWED.fullmatch(value) or _CALL.search(value)
                or _DOUBLE.search(value) or re.search(r'(?:^|[*/(+-])\s*-', value)):  # a negated factor: it may fold
            continue
        text = function.clean[b0:b1]
        use = _word(local).search(text)
        if not use or len(_word(local).findall(text)) != 1 or re.match(r'\s*=(?!=)', text[use.end():]):
            continue
        if function.dead_after(local, second):
            found.append((index, index + 1, local))
    return found[:MAX_INLINES]


def _render(function, holds, inlines, choice, subset):
    """The source with the chosen holds (`choice[i]` a local or None) and the chosen inlines applied."""
    source = function.source
    prefix, body = {}, {}
    for index, (start, stop, _) in enumerate(function.statements):
        body[index] = source[start:stop]
    cut = {}
    for site, carrier in zip(holds, choice):
        if carrier is None:
            continue
        index, (opening, closing), _ = site
        start = function.statements[index][0]
        text = body[index]
        # positions are in the original text: replace through the offsets from the statement's start
        shift = sum(len(a) - len(b) for a, b in cut.get(index, ()))
        inner = source[opening + 1:closing - 1].strip()
        left, right = opening - start + shift, closing - start + shift
        body[index] = text[:left] + carrier + text[right:]
        cut.setdefault(index, []).append((carrier, source[opening:closing]))
        prefix[index] = prefix.get(index, '') + f'{carrier} = {inner}; '
    deleted = set()
    for number in subset:
        first, second, local = inlines[number]
        value = re.fullmatch(r'\s*' + local + r'\s*=\s*(.*?);', body[first], re.S)[1].strip()
        atom = re.fullmatch(r'-?[\w.]+', value) is not None
        body[second] = _word(local).sub((value if atom else f'({value})').replace('\\', '\\\\'), body[second], count=1)
        deleted.add(first)
    pieces, position = [], 0
    for index, (start, stop, _) in enumerate(function.statements):
        pieces.append(source[position:start])
        if index not in deleted:
            pieces.append(prefix.get(index, '') + body[index])
        elif prefix.get(index):
            pieces.append(prefix[index].rstrip())
        position = stop
    pieces.append(source[position:])
    return ''.join(pieces)


def variants(source, name):
    function = _Function(source, name)
    if not function.ok:
        return []
    holds, inlines = _holds(function), _inlines(function)
    if not holds and not inlines:
        return []
    options = [[None, *site[2]] for site in holds]
    configurations = []
    for choice in itertools.product(*options):
        for size in range(len(inlines) + 1):
            for subset in itertools.combinations(range(len(inlines)), size):
                edits = sum(carrier is not None for carrier in choice) + len(subset)
                if edits:
                    # the small edits first, then the biggest bundles: the edits this family exists for are each
                    # no better alone (the saved 85 became 585 with two of three, 0 with all), so a search that only
                    # grows a bundle one edit at a time never gets there
                    rank = (0, edits) if edits <= 2 else (1, -edits)
                    configurations.append((rank, len(configurations), choice, subset))
    configurations.sort()
    result, seen = [], {source}
    for _, _, choice, subset in configurations:
        text = _render(function, holds, inlines, choice, subset)
        if text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result
