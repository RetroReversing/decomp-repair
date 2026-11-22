"""Repairs that a period compiler's own diagnostic points at, for m2c drafts that do not compile.

m2c types addresses loosely: a `void **` plus a `void *`, a function's address plus an offset, an integer dereferenced
as if it held an address, a call through `*(table + index)`. The compiler names the line and the kind of mistake; each
repair here changes only that line, and only the expression the message is about:

* `invalid operands to binary +` (or `-`, `&`, `<<`, ...): the operands next to the operator are read as integers.
* `invalid type argument of `unary *'` / `wrong type argument to bit-complement`: the operand is an address held in an
  integer, so it is cast to a word pointer / read as an integer.
* `called object is not a function`: `*(address)(args)` calls the function pointer stored at `address`.
* `void value not ignored` / `invalid use of void expression`: a `*(a + b)` that m2c left untyped reads a value of the
  type the assigned local has (a byte when that is not known).
* `arithmetic on pointer to an incomplete type`: the same as an invalid binary `+`.
* `pointer value used where a floating point value was expected`: `(f32) p` converts what `p` holds.
* `incompatible type for argument N of `f'`: the callee's declaration drops its parameter list.

The compiler can't be told which of several operators on a line is the wrong one, so `attempt` picks the nth: a caller
that compiles again, and meets the same message on the same line, asks for the next. Nothing here runs a compiler.
"""
import re

_TOKEN = re.compile(r'''\s+|0[xX][0-9a-fA-F]+[uUlL]*|\d+(?:\.\d+)?[fFuUlL]*|[A-Za-z_]\w*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'
                        |<<=|>>=|->|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|\+\+|--|.''', re.X)
_BINARY = re.compile(r'invalid operands to binary (\S+)')
_DIAGNOSTIC = re.compile(r'^func\.c:(\d+): (.*)$')
_OPEN, _CLOSE = {'(': ')', '[': ']'}, {')': '(', ']': '['}
_CAST_WORDS = {'s8', 's16', 's32', 's64', 'u8', 'u16', 'u32', 'u64', 'f32', 'f64', 'int', 'char', 'short', 'long',
               'unsigned', 'signed', 'float', 'double', 'void', 'const', 'volatile', 'struct'}


def diagnostics(log):
    """(line, message) of each error the compiler reported, in order, once per line and message."""
    seen, out = set(), []
    for text in str(log).splitlines():
        found = _DIAGNOSTIC.match(text.strip())
        if found and 'warning' not in found[2] and (found[1], found[2]) not in seen:
            seen.add((found[1], found[2]))
            out.append((int(found[1]), found[2]))
    return out


class _Tokens(list):
    """The tokens of a line (whitespace dropped); `starts` and `ends` say where each one is in the text."""

    def __init__(self, text):
        super().__init__()
        self.starts, self.ends = [], []
        for found in _TOKEN.finditer(text):
            if not found[0].isspace():
                self.append(found[0])
                self.starts.append(found.start())
                self.ends.append(found.end())


def _tokens(text):
    return _Tokens(text)


def _match(tokens, index):
    """Index of the bracket that pairs the one at `index` (either direction), or None."""
    token = tokens[index]
    step, depth = (1, 0) if token in _OPEN else (-1, 0)
    for i in range(index, len(tokens) if step == 1 else -1, step):
        if tokens[i] in _OPEN:
            depth += 1
        elif tokens[i] in _CLOSE:
            depth -= 1
        if depth == 0:
            return i
    return None


def _is_cast(tokens, close):
    """True when the `)` at `close` ends a cast such as `(s32)` or `(void **)`."""
    opening = _match(tokens, close)
    return (opening is not None and close > opening + 1 and tokens[opening] == '('
            and all(t in _CAST_WORDS or t == '*' for t in tokens[opening + 1:close]))


def _operand_end(tokens, i):
    """True when the token before position `i` ends an operand (so an operator at `i` is binary)."""
    if i == 0:
        return False
    last = tokens[i - 1]
    if last == ')':
        return not _is_cast(tokens, i - 1)
    return bool(re.match(r'[\w"\']', last) or last == ']') and last not in _CAST_WORDS


def _name(token):
    return bool(re.match(r'[A-Za-z_]\w*$', token)) and token not in _CAST_WORDS


def _atom_before(tokens, end):
    start = _atom_start(tokens, end)
    # a unary operator in front belongs to the operand (`&func + 8` reads `&func`)
    while start is not None and start > 0 and tokens[start - 1] in ('&', '*', '-', '~', '!') \
            and not _operand_end(tokens, start - 1) and not _in_type(tokens, start - 1):
        start -= 1
    return start


def _atom_start(tokens, end):
    """Start index of the operand that ends just before `end`: a name or number, or a bracketed group with the name
    it calls or indexes (`M2C_FIELD(...)`, `table[i]`) and any further index groups."""
    start = end
    while start > 0:
        last = tokens[start - 1]
        if last in (')', ']'):
            opening = _match(tokens, start - 1)
            if opening is None:
                return None
            start = opening
            if start > 0 and _name(tokens[start - 1]):
                return start - 1
            if start > 0 and tokens[start - 1] == ']':
                continue
            return start
        if re.match(r'[\w"\']', last):
            return start - 1
        return None
    return None


def _atom_after(tokens, start):
    """End index (exclusive) of the operand that begins at `start`, skipping unary prefixes and casts."""
    i = start
    while i < len(tokens):
        if tokens[i] in ('*', '&', '-', '!', '~', '+'):
            i += 1
        elif tokens[i] == '(' and (close := _match(tokens, i)) and all(t in _CAST_WORDS or t == '*' for t in tokens[i + 1:close]) \
                and close > i + 1:
            i = close + 1
        else:
            break
    if i >= len(tokens):
        return None
    if tokens[i] == '(':
        i = _match(tokens, i)
        if i is None:
            return None
        i += 1
    elif re.match(r'[\w"\']', tokens[i]):
        i += 1
    else:
        return None
    while i < len(tokens) and tokens[i] in ('(', '['):
        i = _match(tokens, i)
        if i is None:
            return None
        i += 1
    return i


def _binary_operators(tokens, op):
    return [i for i, token in enumerate(tokens) if token == op and _operand_end(tokens, i)]


def _in_type(tokens, i):
    """True for a `*` that is part of a type (`(s32 *)`, `void ***`), not an operator."""
    while i > 0 and tokens[i - 1] == '*':
        i -= 1
    return i > 0 and tokens[i - 1] in _CAST_WORDS


def _unary_operators(tokens, op):
    return [i for i, token in enumerate(tokens)
            if token == op and not _operand_end(tokens, i) and not _in_type(tokens, i)]


def _binary(tokens, op, attempt):
    places = _binary_operators(tokens, op) + [i for i in _binary_operators(tokens, op + '=')]
    places.sort()
    if attempt >= len(places):
        return None
    at = places[attempt]
    if tokens[at] == op + '=':  # `*p += q`: the target stays as it is, the amount is an integer
        right = _atom_after(tokens, at + 1)
        return None if right is None else [(tokens.starts[at + 1], '(s32)')]
    left, right = _atom_before(tokens, at), _atom_after(tokens, at + 1)
    if left is None or right is None:
        return None
    return [(tokens.starts[left], '(s32)'), (tokens.starts[at + 1], '(s32)')]


def _dereference(tokens, attempt, cast):
    places = _unary_operators(tokens, '*')
    if attempt >= len(places) or _atom_after(tokens, places[attempt] + 1) is None:
        return None
    return [(tokens.starts[places[attempt] + 1], cast)]


def _complement(tokens, attempt):
    places = _unary_operators(tokens, '~')
    if attempt >= len(places) or _atom_after(tokens, places[attempt] + 1) is None:
        return None
    return [(tokens.starts[places[attempt] + 1], '(s32)')]


def _call_through_table(tokens, attempt):
    """`*(address)(args)` -> `((s32 (*)()) *(s32 *)(address))(args)`: the call of the pointer stored at `address`."""
    places = []
    for at in _unary_operators(tokens, '*'):
        if tokens[at + 1:at + 2] == ['(']:
            close = _match(tokens, at + 1)
            if close is not None and tokens[close + 1:close + 2] == ['(']:
                places.append((at, close))
    if attempt >= len(places):
        return None
    at, close = places[attempt]
    return [(tokens.starts[at], '((s32 (*)()) '), (tokens.starts[at + 1], '(s32 *)'), (tokens.ends[close], ')')]


_SCALARS = ('f32', 'f64', 's8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64')


def _read_type(source, line_text):
    """The type a `*(a + b)` of unknown type is read as: that of the local it is assigned to, else a byte."""
    target = re.match(r'\s*(\w+)\s*=[^=]', line_text)
    if target:
        declared = re.search(r'^[ \t]+(' + '|'.join(_SCALARS) + r')[ \t]+' + re.escape(target[1]) + r'\b', source, re.M)
        if declared:
            return declared[1]
    return 'u8'


def _untyped_read(tokens, attempt, kind):
    places = [at for at in _unary_operators(tokens, '*') if tokens[at + 1:at + 2] == ['(']]
    if attempt >= len(places):
        return None
    return [(tokens.starts[places[attempt] + 1], f'({kind} *)')]


def _float_conversion(tokens, attempt):
    places = [i for i in range(len(tokens) - 3)
              if tokens[i] == '(' and tokens[i + 1] in ('f32', 'f64') and tokens[i + 2] == ')'
              and _atom_after(tokens, i + 3) is not None]
    if attempt >= len(places):
        return None
    return [(tokens.starts[places[attempt] + 3], '(s32)')]


def _drop_parameters(source, name):
    """`source` with the declaration of `name` left without a parameter list, or None."""
    declaration = re.compile(r'^(?P<head>[A-Za-z_][^\n;()=]*\b' + re.escape(name) + r')\((?P<params>[^()\n]+)\);', re.M)
    found = declaration.search(source)
    if not found or found['params'].strip() == 'void':
        return None
    return source[:found.start()] + found['head'] + '();' + source[found.end():]


def repair(source, line, message, attempt=0):
    """`source` with line `line` (1-based) changed for the compiler's `message`, or None when nothing fits."""
    if (found := re.search(r"incompatible type for argument \d+ of `(\w+)'", message)):
        return _drop_parameters(source, found[1]) if attempt == 0 else None
    lines = source.split('\n')
    if not 1 <= line <= len(lines):
        return None
    text = lines[line - 1]
    code = text[:cut] if (cut := text.find('/*')) >= 0 else text
    tokens = _tokens(code)
    if found := _BINARY.search(message):
        edits = _binary(tokens, found[1], attempt)
    elif 'arithmetic on pointer to an incomplete type' in message:
        edits = _binary(tokens, '+', attempt) or _binary(tokens, '-', attempt - len(_binary_operators(tokens, '+')))
    elif 'void value not ignored' in message or 'invalid use of void expression' in message:
        edits = _untyped_read(tokens, attempt, _read_type(source, code))
    elif 'pointer value used where a floating point value was expected' in message:
        edits = _float_conversion(tokens, attempt)
    elif 'invalid type argument of `unary *' in message:
        edits = _dereference(tokens, attempt, '(s32 *)')
    elif 'wrong type argument to bit-complement' in message:
        edits = _complement(tokens, attempt)
    elif 'called object is not a function' in message:
        edits = _call_through_table(tokens, attempt)
    else:
        return None
    if not edits:
        return None
    for position, insert in sorted(edits, reverse=True):
        text = text[:position] + insert + text[position:]
    lines[line - 1] = text
    return '\n'.join(lines)
