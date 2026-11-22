"""A small C expression reader with types, shared by the families that regroup or hold sub-expressions.

`temporary_hoist_repairs` and `reassociation_repairs` have to know what an expression is: where a sub-expression
begins and ends, whether it may be evaluated earlier or in another order (no call, no side effect, no volatile), and
what type it has (the temporary needs one; a regrouping is only the same value when the types make it so). Text
patterns can't say that reliably, so this module reads a statement into a tree:

- `sites(source, span)` lists the function's expressions with the statement each belongs to (an expression
  statement, a `return`, a condition, a declaration's initializer) and the block it is in;
- `Parser` reads one expression into `Node`s (binary, unary, cast, call, index, member, ...) carrying their offsets in
  the source, so a family edits the exact text and leaves everything else untouched;
- `Types` knows the declared type of every name (parameters, locals, file-level declarations, the header's, struct
  members by name when every struct agrees) and `Types.of(node)` gives an expression its C type, or None when
  anything in it is unknown (a macro, an unknown typedef, a plain `char`): a family then skips it.

Integers are 32-bit `int` (a 64-bit `long long`); the readers refuse a source whose `int` is not. Nothing here
decides a match: it only says what a rewrite may keep exact.
"""
import re
from dataclasses import dataclass

from .csource import _blank, find

IDENT = r'[A-Za-z_]\w*'
QUALIFIERS = {'const', 'volatile', 'register', 'static', 'extern', 'auto', 'inline'}
KEYWORD_TYPES = {'unsigned', 'signed', 'int', 'char', 'short', 'long', 'float', 'double', 'void', 'struct', 'union', 'enum'}
DEFAULT_TYPEDEFS = {'s8': (8, True), 'u8': (8, False), 's16': (16, True), 'u16': (16, False), 's32': (32, True),
                    'u32': (32, False), 's64': (64, True), 'u64': (64, False)}
STATEMENT_KEYWORDS = {'return', 'if', 'else', 'while', 'for', 'do', 'switch', 'goto', 'break', 'continue', 'case',
                      'default', 'typedef', 'sizeof'}
ASSIGN_OPS = {'=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='}
PRECEDENCE = {'||': 1, '&&': 2, '|': 3, '^': 4, '&': 5, '==': 6, '!=': 6, '<': 7, '>': 7, '<=': 7, '>=': 7,
              '<<': 8, '>>': 8, '+': 9, '-': 9, '*': 10, '/': 10, '%': 10}

_TOKEN = re.compile(r'''\s*(?:
    (?P<num>0[xX][0-9a-fA-F]+[uUlL]*|\d+\.\d*(?:[eE][-+]?\d+)?[fFlL]?|\.\d+(?:[eE][-+]?\d+)?[fFlL]?
        |\d+[eE][-+]?\d+[fFlL]?|\d+[uUlL]*)
    |(?P<id>[A-Za-z_]\w*)
    |(?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
    |(?P<op><<=|>>=|\+\+|--|->|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|[-+*/%&|^~!<>=?:.,()\[\]])
)''', re.X)


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class Ty:
    kind: str  # 'int', 'float', 'ptr', 'void' or 'opaque' (a struct by value)
    bits: int = 32
    signed: bool = True
    spelling: str = 'int'
    target: 'Ty | None' = None  # what a pointer points to


INT = Ty('int', 32, True, 'int')
UINT = Ty('int', 32, False, 'unsigned int')
LLONG = Ty('int', 64, True, 'long long')
ULLONG = Ty('int', 64, False, 'unsigned long long')
FLOAT = Ty('float', 32, True, 'float')
DOUBLE = Ty('float', 64, True, 'double')


class Node:
    """One expression: `kind`, an operator or name in `op`, children in `kids`, and `start:end` in the source."""
    __slots__ = ('kind', 'op', 'kids', 'start', 'end', 'info')

    def __init__(self, kind, op, kids, start, end, info=None):
        self.kind, self.op, self.kids, self.start, self.end, self.info = kind, op, kids, start, end, info

    def walk(self):
        yield self
        for kid in self.kids:
            yield from kid.walk()


def tokenize(text, base=0):
    tokens, at = [], 0
    while at < len(text):
        match = _TOKEN.match(text, at)
        if not match:
            if text[at:].strip():
                raise ParseError('unreadable text')
            break
        kind = match.lastgroup
        tokens.append((kind, match.group(kind), base + match.start(kind), base + match.end(kind)))
        at = match.end()
    return tokens


class Parser:
    """Reads one expression (or a comma list); `typenames` are the typedef names a cast may use."""

    def __init__(self, text, base, typenames):
        self.tokens = tokenize(text, base)
        self.at = 0
        self.typenames = typenames

    def peek(self, offset=0):
        i = self.at + offset
        return self.tokens[i] if i < len(self.tokens) else (None, None, None, None)

    def take(self, value=None):
        token = self.peek()
        if token[0] is None or (value is not None and token[1] != value):
            raise ParseError(f'expected {value}')
        self.at += 1
        return token

    def parse(self):
        node = self.comma()
        if self.at != len(self.tokens):
            raise ParseError('trailing text')
        return node

    def comma(self):
        node = self.assignment()
        while self.peek()[1] == ',' and self.peek()[0] == 'op':
            self.take()
            right = self.assignment()
            node = Node('comma', ',', [node, right], node.start, right.end)
        return node

    def assignment(self):
        left = self.conditional()
        kind, value, *_ = self.peek()
        if kind == 'op' and value in ASSIGN_OPS:
            self.take()
            right = self.assignment()
            return Node('assign', value, [left, right], left.start, right.end)
        return left

    def conditional(self):
        condition = self.binary(1)
        if self.peek()[:2] == ('op', '?'):
            self.take()
            yes = self.comma()
            self.take(':')
            no = self.conditional()
            return Node('cond', '?', [condition, yes, no], condition.start, no.end)
        return condition

    def binary(self, minimum):
        left = self.unary()
        while True:
            kind, value, *_ = self.peek()
            level = PRECEDENCE.get(value) if kind == 'op' else None
            if level is None or level < minimum:
                return left
            self.take()
            right = self.binary(level + 1)
            left = Node('binary', value, [left, right], left.start, right.end)

    def _cast_end(self):
        """Index of the `)` closing a cast that starts at the current `(`, or None when it isn't a cast."""
        i, seen = self.at + 1, False
        while i < len(self.tokens):
            kind, value, *_ = self.tokens[i]
            if kind == 'op' and value == ')':
                break
            if kind == 'op' and value == '*':
                i += 1
                continue
            known = kind == 'id' and (value in KEYWORD_TYPES or value in QUALIFIERS or value in self.typenames
                                      or (i > self.at + 1 and self.tokens[i-1][1] in ('struct', 'union', 'enum')))
            if not known:
                return None
            seen = seen or value not in QUALIFIERS
            i += 1
        else:
            return None
        after = self.tokens[i+1] if i + 1 < len(self.tokens) else None
        if not seen or after is None:
            return None
        if after[0] in ('num', 'id', 'str') or after[1] in ('(', '-', '+', '!', '~', '*', '&', '++', '--'):
            return i
        return None

    def unary(self):
        kind, value, start, _ = self.peek()
        if kind == 'op' and value in ('-', '+', '!', '~', '*', '&', '++', '--'):
            self.take()
            kid = self.unary()
            return Node('unary', value, [kid], start, kid.end)
        if kind == 'id' and value == 'sizeof':
            self.take()
            if self.peek()[1] == '(':
                depth = 0
                while True:
                    token = self.take()
                    depth += (token[1] == '(') - (token[1] == ')')
                    if not depth:
                        return Node('sizeof', 'sizeof', [], start, token[3])
            kid = self.unary()
            return Node('sizeof', 'sizeof', [], start, kid.end)
        if kind == 'op' and value == '(':
            close = self._cast_end()
            if close is not None:
                words = tuple(token[1] for token in self.tokens[self.at+1:close])
                self.at = close + 1
                kid = self.unary()
                return Node('cast', 'cast', [kid], start, kid.end, words)
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while True:
            kind, value, *_ = self.peek()
            if kind != 'op':
                return node
            if value == '[':
                self.take()
                index = self.comma()
                end = self.take(']')[3]
                node = Node('index', '[]', [node, index], node.start, end)
            elif value == '(':
                self.take()
                args = []
                if self.peek()[1] != ')':
                    args.append(self.assignment())
                    while self.peek()[1] == ',':
                        self.take()
                        args.append(self.assignment())
                end = self.take(')')[3]
                node = Node('call', '()', [node] + args, node.start, end)
            elif value in ('.', '->'):
                self.take()
                field = self.take()
                if field[0] != 'id':
                    raise ParseError('member name')
                node = Node('member', value, [node], node.start, field[3], field[1])
            elif value in ('++', '--'):
                self.take()
                node = Node('postfix', value, [node], node.start, self.tokens[self.at-1][3])
            else:
                return node

    def primary(self):
        kind, value, start, end = self.peek()
        if kind in ('num', 'id', 'str'):
            self.take()
            return Node(kind, value, [], start, end)
        if kind == 'op' and value == '(':
            self.take()
            inner = self.comma()
            close = self.take(')')
            return Node('paren', '()', [inner], start, close[3])
        raise ParseError('expression expected')


def parse(text, start, end, typenames=()):
    """The expression `text[start:end]` as a tree, or None when it is not one this reader understands."""
    try:
        return Parser(text[start:end], start, set(typenames)).parse()
    except ParseError:
        return None


def bare(node):
    """The node without its parentheses."""
    while node.kind == 'paren':
        node = node.kids[0]
    return node


def key(node):
    """A structural key: equal for two spellings of one expression (spacing and redundant parentheses ignored)."""
    node = bare(node)
    return (node.kind, node.op, node.info, tuple(key(kid) for kid in node.kids))


def names(node):
    """Every identifier an expression reads (members and callees excluded)."""
    return {n.op for n in node.walk() if n.kind == 'id'}


def pure(node):
    """No call, assignment, increment or string: evaluating it twice, earlier or later gives the same value
    as long as the variables it reads don't change."""
    return not any(n.kind in ('call', 'assign', 'postfix', 'comma', 'str', 'sizeof', 'cond')
                   or (n.kind == 'unary' and n.op in ('++', '--')) for n in node.walk())


# ---------------------------------------------------------------- types

def _spell(bits, signed, hints):
    for hint in hints:
        if hint is not None and hint.kind == 'int' and (hint.bits, hint.signed) == (bits, signed):
            return hint.spelling
    return {(32, True): 'int', (32, False): 'unsigned int', (64, True): 'long long',
            (64, False): 'unsigned long long'}[bits, signed]


def promote(ty):
    return ty if ty.bits >= 32 else INT


def arithmetic(a, b):
    """The usual arithmetic conversions of two numeric types."""
    if a.kind == 'float' or b.kind == 'float':
        if a.kind == 'float' and b.kind == 'float':
            return a if a.bits >= b.bits else b
        return a if a.kind == 'float' else b
    a, b = promote(a), promote(b)
    if a.bits != b.bits:
        wide = a if a.bits > b.bits else b
        return Ty('int', wide.bits, wide.signed, _spell(wide.bits, wide.signed, (a, b)))
    signed = a.signed and b.signed
    return Ty('int', a.bits, signed, _spell(a.bits, signed, (a, b)))


def literal_value(text):
    lowered = text.lower().rstrip('ul')
    return int(lowered, 16) if lowered.startswith('0x') else int(lowered, 8 if len(lowered) > 1 and lowered[0] == '0' else 10)


def int_range(ty):
    if ty.bits >= 64 and not ty.signed:
        return 0, 2**64 - 1
    return (-(2 ** (ty.bits - 1)), 2 ** (ty.bits - 1) - 1) if ty.signed else (0, 2 ** ty.bits - 1)


class Types:
    """The declared types of a function's names, from its own text, the file's and the header's."""

    def __init__(self, source, name, header=''):
        self.volatile, self.unknown = set(), set()
        self.table = {}
        self.typedefs = {n: Ty('int', bits, signed, n) for n, (bits, signed) in DEFAULT_TYPEDEFS.items()}
        self.typedefs.update({'f32': Ty('float', 32, True, 'f32'), 'f64': Ty('float', 64, True, 'f64')})
        self.members = {}
        self.ok = False
        self.body_start = self.body_end = 0
        text = _blank(header + '\n' + source)
        self._typedefs(text)
        self._members(text)
        self.locals = set()
        span = find(source, name)
        if not span:
            return
        body = _blank(source)[span[0]:span[1]]
        opening = body.find('{')
        if opening < 0:
            return
        self.body_start = span[0] + opening
        self.body_end = span[1]
        self.ok = True
        offset = len(header) + 1
        outside = text[:offset + span[0]] + ' ' * (span[1] - span[0]) + text[offset + span[1]:]
        self._declarations(outside, local=False)
        signature = body[:opening]
        paren = signature.find('(')
        if paren >= 0:
            depth, close = 0, None
            for i in range(paren, len(signature)):
                depth += (signature[i] == '(') - (signature[i] == ')')
                if depth == 0:
                    close = i
                    break
            if close is not None:
                for part in self._split(signature[paren+1:close], ','):
                    self._declare(part, local=True)
                self._declarations(signature[close+1:] + ';', local=True)
        self._declarations(body[opening:], local=True)
        for ambiguous in self.unknown:
            self.table.pop(ambiguous, None)

    @staticmethod
    def _split(text, separator):
        parts, depth, begin = [], 0, 0
        for i, ch in enumerate(text):
            depth += (ch in '([{') - (ch in ')]}')
            if ch == separator and depth == 0:
                parts.append(text[begin:i])
                begin = i + 1
        parts.append(text[begin:])
        return parts

    def _typedefs(self, text):
        for match in re.finditer(r'\btypedef\s+([^;{}]+?)\s*;', text):
            words = match[1].replace('*', ' * ').split()
            if len(words) >= 2 and re.fullmatch(IDENT, words[-1]) and '*' not in words:
                base = self.base_type(words[:-1])
                if base is not None:
                    self.typedefs[words[-1]] = Ty(base.kind, base.bits, base.signed, words[-1], base.target)

    def _members(self, text):
        for match in re.finditer(r'\b(?:struct|union)\s*(?:' + IDENT + r')?\s*{', text):
            depth, i = 0, match.end() - 1
            while i < len(text):
                depth += (text[i] == '{') - (text[i] == '}')
                if depth == 0:
                    break
                i += 1
            inner = text[match.end():i]
            if '{' in inner:
                continue
            for member in inner.split(';'):
                self._declare(member, members=True)

    def _declarations(self, text, local):
        """Declarations at statement level (a `;` after a type word) in `text`; file-level ones skip braces."""
        depth, braces, begin = 0, 0, 0
        for i, ch in enumerate(text):
            depth += (ch == '(') - (ch == ')')
            if depth:
                continue
            if ch in ';{}':
                piece = text[begin:i].strip()
                if ch == ';' and piece and (local or braces == 0) and self._is_declaration(piece):
                    self._declare(piece, local=local)
                begin = i + 1
                braces += (ch == '{') - (ch == '}')

    def _is_declaration(self, piece):
        words = re.findall(IDENT + r'|\*', piece)
        if not words:
            return False
        first = words[0]
        if first in STATEMENT_KEYWORDS:
            return False
        if first in KEYWORD_TYPES or first in QUALIFIERS or first in self.typedefs:
            return True
        return len(words) >= 2 and re.match(IDENT + r'\s+\**\s*' + IDENT + r'\s*(?:[\[=,;]|$)', piece) is not None

    def base_type(self, words):
        words = [w for w in words if w not in QUALIFIERS]
        if not words:
            return None
        if words[0] in ('struct', 'union', 'enum'):
            return Ty('opaque', spelling=' '.join(words)) if words[0] != 'enum' else INT
        if len(words) == 1 and words[0] in self.typedefs:
            return self.typedefs[words[0]]
        if any(w not in KEYWORD_TYPES for w in words):
            return None
        unsigned = 'unsigned' in words
        if 'void' in words:
            return Ty('void', spelling='void')
        if 'float' in words:
            return FLOAT
        if 'double' in words:
            return DOUBLE
        spelling = ' '.join(words)
        if 'char' in words:
            return Ty('int', 8, False, spelling) if unsigned else (Ty('int', 8, True, spelling) if 'signed' in words else None)
        if 'short' in words:
            return Ty('int', 16, not unsigned, spelling)
        if words.count('long') >= 2:
            return Ty('int', 64, not unsigned, spelling)
        return Ty('int', 32, not unsigned, spelling)

    def _declare(self, piece, members=False, local=False):
        piece = piece.strip()
        if not piece or '(' in piece.split('=')[0]:
            return
        declarators = self._split(piece, ',')
        words = re.findall(IDENT + r'|\*', declarators[0].split('=')[0].split('[')[0])
        if len(words) < 2 or words[-1] == '*':
            return
        name_ = words[-1]
        stars = 0
        base_words = []
        for word in words[:-1]:
            if word == '*':
                stars += 1
            else:
                base_words.append(word)
        base = self.base_type(base_words)
        is_volatile = 'volatile' in base_words
        for n, declarator in enumerate(declarators):
            if n:
                left = declarator.split('=')[0].split('[')[0]
                found = re.findall(IDENT + r'|\*', left)
                if not found or found[-1] == '*':
                    continue
                name_, stars = found[-1], found.count('*')
            array = '[' in declarator.split('=')[0]
            if ':' in declarator:
                continue
            ty = base
            if ty is not None:
                for _ in range(stars + (1 if array else 0)):
                    spelling = ty.spelling + ('*' if ty.spelling.endswith('*') else ' *')
                    ty = Ty('ptr', 32, False, spelling, ty)
            table = self.members if members else self.table
            if name_ in table and table[name_] != ty:
                (self.members if members else self.table)[name_] = None
                if not members:
                    self.unknown.add(name_)
            else:
                table[name_] = ty
            if is_volatile:
                self.volatile.add(name_)
            if local and not members:
                self.locals.add(name_)

    # ---- the type of an expression

    def of(self, node):
        try:
            return self._of(node)
        except (KeyError, TypeError):
            return None

    def _of(self, node):
        kind = node.kind
        if kind == 'paren':
            return self._of(node.kids[0])
        if kind == 'num':
            return self._literal(node.op)
        if kind == 'id':
            return self.table.get(node.op)
        if kind == 'cast':
            return self._cast(node)
        if kind == 'member':
            return self.members.get(node.info)
        if kind == 'index':
            base = self._of(node.kids[0])
            index = self._of(node.kids[1])
            return base.target if base is not None and base.kind == 'ptr' and index is not None and index.kind == 'int' else None
        if kind == 'unary':
            inner = self._of(node.kids[0])
            if inner is None:
                return None
            if node.op in ('-', '+', '~'):
                return promote(inner) if inner.kind == 'int' else (inner if inner.kind == 'float' and node.op != '~' else None)
            if node.op == '!':
                return INT
            if node.op == '*':
                return inner.target if inner.kind == 'ptr' else None
            if node.op == '&':
                return Ty('ptr', 32, False, inner.spelling + ('*' if inner.spelling.endswith('*') else ' *'), inner)
            return None
        if kind == 'binary':
            return self._binary(node)
        return None

    def _cast(self, node):
        words = list(node.info)
        stars = words.count('*')
        base = self.base_type([w for w in words if w != '*'])
        if base is None:
            return None
        for _ in range(stars):
            base = Ty('ptr', 32, False, base.spelling + ('*' if base.spelling.endswith('*') else ' *'), base)
        return base

    @staticmethod
    def _literal(text):
        lowered = text.lower()
        if lowered.startswith('0x') or re.fullmatch(r'\d+[ul]*', lowered):
            value = literal_value(text)
            hexadecimal = lowered.startswith('0x') or (len(lowered) > 1 and lowered.startswith('0'))
        else:
            return FLOAT if lowered.endswith('f') else DOUBLE
        suffix = lowered[len(lowered.rstrip('ul')):]
        unsigned = 'u' in suffix
        if suffix.count('l') >= 2 or value > 0xFFFFFFFF:
            return ULLONG if unsigned or value > 0x7FFFFFFFFFFFFFFF else LLONG
        if value <= 0x7FFFFFFF and not unsigned:
            return INT
        return UINT if (unsigned or hexadecimal or value > 0x7FFFFFFF) else INT

    def _binary(self, node):
        left, right = (self._of(kid) for kid in node.kids)
        if left is None or right is None:
            return None
        op = node.op
        if op in ('==', '!=', '<', '>', '<=', '>=', '&&', '||'):
            return INT
        if op in ('<<', '>>'):
            return promote(left) if left.kind == 'int' and right.kind == 'int' else None
        if left.kind == 'ptr' or right.kind == 'ptr':
            if op == '+' and left.kind == 'ptr' and right.kind == 'int':
                return left
            if op == '+' and right.kind == 'ptr' and left.kind == 'int':
                return right
            if op == '-' and left.kind == 'ptr' and right.kind == 'int':
                return left
            if op == '-' and left.kind == 'ptr' and right.kind == 'ptr':
                return INT
            return None
        if left.kind not in ('int', 'float') or right.kind not in ('int', 'float'):
            return None
        if op in ('%', '&', '|', '^') and 'float' in (left.kind, right.kind):
            return None
        return arithmetic(left, right)

    def interval(self, node):
        """(low, high) of an integer expression's value, from its type and the literals and masks in it."""
        ty = self.of(node)
        if ty is None or ty.kind != 'int':
            return None
        full = int_range(ty)
        node = bare(node)
        if node.kind == 'num':
            return (literal_value(node.op),) * 2
        if node.kind == 'cast':
            inner = self.interval(node.kids[0])
            low, high = int_range(ty)
            return inner if inner and low <= inner[0] and inner[1] <= high else (low, high)
        if node.kind == 'binary':
            a, b = self.interval(node.kids[0]), self.interval(node.kids[1])
            if a is None or b is None:
                return full
            op = node.op
            result = None
            if op == '+':
                result = (a[0] + b[0], a[1] + b[1])
            elif op == '-':
                result = (a[0] - b[1], a[1] - b[0])
            elif op == '*':
                corners = [x * y for x in a for y in b]
                result = (min(corners), max(corners))
            elif op == '&' and (a[0] >= 0 or b[0] >= 0):
                highs = [x[1] for x in (a, b) if x[0] >= 0]
                result = (0, min(highs))
            elif op == '<<' and b[0] == b[1] and 0 <= b[0] < 32 and a[0] >= 0:
                result = (a[0] << b[0], a[1] << b[0])
            elif op == '>>' and b[0] == b[1] and 0 <= b[0] < 32 and a[0] >= 0:
                result = (a[0] >> b[0], a[1] >> b[0])
            elif op == '%' and b[0] == b[1] and b[0] > 0:
                result = (0 if a[0] >= 0 else -(b[0] - 1), b[0] - 1)
            if result is not None and full[0] <= result[0] and result[1] <= full[1]:
                return result
        return full


# ---------------------------------------------------------------- statements

@dataclass
class Site:
    """One expression of the function and where it sits.

    `kind`: 'expr', 'return', 'if', 'while', 'for', 'switch' or 'init' (a declaration's initializer).
    `statement`: where a statement inserted before this one goes, or None when no statement may be put there
    (an unbraced body, an `else`, the middle of a loop header). `block`: the `{` of the enclosing block.
    `index`: the order among the function's statements."""
    kind: str
    start: int
    end: int
    statement: int | None
    block: int
    index: int
    declaration: bool = False
    labeled: bool = False


_LABEL = re.compile(r'(?:case\b[^:?;]*:(?!:)|default\s*:|' + IDENT + r'\s*:(?!:))\s*')
_HEADER = re.compile(r'(if|while|for|switch)\s*\(')


def _match(text, at):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == '(') - (text[i] == ')')
        if depth == 0:
            return i
    return None


def _top_split(text, begin, end, separator):
    """Offsets of the top-level `separator`s of text[begin:end]."""
    depth, found = 0, []
    for i in range(begin, end):
        depth += (text[i] in '([{') - (text[i] in ')]}')
        if depth == 0 and text[i] == separator:
            found.append(i)
    return found


def sites(source, types):
    """Every statement and header expression of the function, in order, as `Site`s (see its docstring)."""
    clean = _blank(source)
    opening, end = types.body_start, types.body_end
    result, blocks = [], [opening]
    begin, depth = opening + 1, 0
    for i in range(opening + 1, end):
        ch = clean[i]
        depth += (ch == '(') - (ch == ')')
        if depth > 0 or ch not in ';{}':
            continue
        if i > begin and clean[begin:i].strip():
            _statement(clean, begin, i, blocks[-1], result, types)
        begin = i + 1
        if ch == '{':
            blocks.append(i)
        elif ch == '}' and len(blocks) > 1:
            blocks.pop()
    return result


def _statement(clean, begin, end, block, result, types):
    at = begin
    reachable, has_else, labeled = True, False, False
    while True:
        while at < end and clean[at].isspace():
            at += 1
        word = re.match(r'else\b', clean[at:end])
        if word:
            at += word.end()
            has_else = True
            reachable = False
            continue
        label = _LABEL.match(clean, at, end)
        if label and not re.match(r'(?:if|while|for|switch|return|else|do)\b', clean[at:end]):
            at = label.end()
            labeled = True
            continue
        if re.match(r'do\b', clean[at:end]):
            at += 2
            reachable = False
            continue
        header = _HEADER.match(clean, at, end)
        if header:
            close = _match(clean, header.end() - 1)
            if close is None or close >= end:
                return
            keyword = header[1]
            statement = at if reachable and keyword == 'if' else None
            inner_begin, inner_end = header.end(), close
            if keyword == 'for':
                cuts = [inner_begin - 1] + _top_split(clean, inner_begin, inner_end, ';') + [inner_end]
                for a, b in zip(cuts, cuts[1:]):
                    if clean[a+1:b].strip():
                        result.append(Site('for', a + 1, b, None, block, len(result)))
            elif clean[inner_begin:inner_end].strip():
                result.append(Site(keyword, inner_begin, inner_end, statement, block, len(result), labeled=labeled))
            at = close + 1
            reachable = False
            continue
        break
    text = clean[at:end]
    if not text.strip():
        return
    statement = at if reachable and not has_else else None
    ret = re.match(r'return\b', text)
    if ret:
        if text[ret.end():].strip():
            result.append(Site('return', at + ret.end(), end, statement, block, len(result), labeled=labeled))
        return
    first = re.match(r'\s*(' + IDENT + ')', text)
    if first and first[1] in STATEMENT_KEYWORDS and first[1] != 'sizeof':
        return
    declaration = types._is_declaration(text.strip())
    if declaration:
        result.append(Site('declaration', at, end, None, block, len(result), declaration=True))
        for cut_begin, cut_end in _declarators(clean, at, end):
            result.append(Site('init', cut_begin, cut_end, None, block, len(result), declaration=True))
        return
    result.append(Site('expr', at, end, statement, block, len(result), labeled=labeled))


def _declarators(clean, begin, end):
    spans = []
    cuts = [begin - 1] + _top_split(clean, begin, end, ',') + [end]
    for a, b in zip(cuts, cuts[1:]):
        eq = None
        depth = 0
        for i in range(a + 1, b):
            depth += (clean[i] in '([{') - (clean[i] in ')]}')
            if depth == 0 and clean[i] == '=':
                eq = i
                break
        if eq is not None and clean[eq+1:b].strip() and not clean[eq+1:b].lstrip().startswith('{'):
            spans.append((eq + 1, b))
    return spans


# ---------------------------------------------------------------- chains

ASSOCIATIVE = ('+', '*', '|', '&', '^')


def chain(node):
    """(op, operands, shape) of the maximal chain `node` roots, or None: `a + (b + c) + d` is `+` over a, b, c, d.
    `shape` nests operand indices the way the source groups them."""
    node = bare(node)
    if node.kind != 'binary' or node.op not in ASSOCIATIVE:
        return None
    operands = []

    def flatten(n):
        inner = bare(n)
        if inner.kind == 'binary' and inner.op == node.op:
            return (flatten(inner.kids[0]), flatten(inner.kids[1]))
        operands.append(n)
        return len(operands) - 1

    shape = flatten(node)
    return node.op, operands, shape


def regroupings(count, shape):
    """Other ways to group `count` operands (`shape` is the source's): a right nest, (four) two halves, then pairs
    gathered first or last. Operand order inside a pair is kept; shapes are nested index tuples."""
    found = []

    def add(candidate):
        if candidate != shape and candidate not in found:
            found.append(candidate)

    indices = list(range(count))
    nest = indices[-1]
    for i in reversed(indices[:-1]):
        nest = (i, nest)
    add(nest)
    if count == 4:
        add(((0, 1), (2, 3)))
        add(((0, 2), (1, 3)))
        add(((0, 3), (1, 2)))
    for a in range(count):
        for b in range(a + 1, count):
            rest = [i for i in indices if i not in (a, b)]
            pair = (a, b)
            front = pair
            for i in rest:
                front = (front, i)
            back = rest[0]
            for i in rest[1:]:
                back = (back, i)
            add(front)
            add((back, pair))
    return found


def render(shape, texts, op, top=True):
    if isinstance(shape, int):
        return texts[shape]
    left, right = (render(part, texts, op, top=False) for part in shape)
    text = f'{left} {op} {right}'
    return text if top else f'({text})'


def exact_regrouping(types, op, operands):
    """True when every grouping and order of `operands` under `op` is the same value in C.

    Bitwise operators always are. `+` and `*` are when the result type wraps (unsigned), when no partial sum or
    product can overflow a signed result (the operands' ranges, from their types, literals and masks, prove it), or
    for pointer arithmetic (`p + a + b`: the original is only defined when its offsets stay inside one object, so the
    integer part `a + b` fits an int). Floating-point operands are never offered, nor is a mix of integer types
    whose partial results would change type with the grouping (the operands, after promotion, must share one)."""
    if len(operands) < 3 or not all(pure(o) for o in operands):
        return False
    tys = [types.of(o) for o in operands]
    if any(t is None or t.kind not in ('int', 'ptr') for t in tys):
        return False
    pointers = [t for t in tys if t.kind == 'ptr']
    if pointers and (op != '+' or len(pointers) > 1):
        return False
    shared = {(promote(t).bits, promote(t).signed) for o, t in zip(operands, tys)
              if t.kind == 'int' and bare(o).kind != 'num'}
    if len(shared) > 1:
        return False
    bits, signed = next(iter(shared)) if shared else (32, True)
    for o, t in zip(operands, tys):
        if bare(o).kind == 'num' and t.kind == 'int' and (t.bits, t.signed) != (bits, signed):
            if t != INT or bits < 32:  # an int literal converts to a wider or unsigned operand without changing the sum
                return False
    if op in ('|', '&', '^'):
        return True
    if not signed or pointers:
        return True
    ranges = [types.interval(o) for o in operands]
    if any(r is None for r in ranges):
        return False
    low, high = int_range(Ty('int', bits, signed))
    if op == '+':
        return sum(min(0, r[0]) for r in ranges) >= low and sum(max(0, r[1]) for r in ranges) <= high
    biggest = 1
    for r in ranges:
        biggest *= max(1, abs(r[0]), abs(r[1]))
    return biggest <= high
