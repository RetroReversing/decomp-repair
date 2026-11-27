"""A quotient or remainder taken in the variable that holds its dividend: `n = a - b; n %= 5;`.

GCC computes a signed division by a constant from the dividend's pseudo, and the remainder is `dividend - quotient *
K`. Written `n = (a - b) % 5;` (or inline in a larger expression) the difference and the remainder are two pseudos and
take two registers; written `n = a - b; n %= 5;` they are one, so the subtraction overwrites the dividend's register
(`subu $a0, $a0, $v1`), as it does in the target. On an N64 function (SN GCC 2.8.1, 124 instructions) a typed
rewrite's eight register rows were this one split (50 -> 10), and from m2c's inline spelling the split had to stand
above the constant store the draft placed before the statement (510 -> 0 with the other edits in place; below the
store 510 stayed 510, and `n = (..) % 5;` above it gave 40). No other family wrote a `%=` for that function.

dividend_in_place
    `V = (X) % K;` with V a local becomes `V = X; V %= K;`. A `(X) % K` (or `/ K`) inside a larger statement gets a
    local of its own (`repair_dividend = X; repair_dividend %= K;`) before the statement, and, as further children,
    above up to two constant stores before it, when they write members X does not read. X has no calls and no side
    effects, K is an integer literal. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, view

FAMILY = 'dividend_in_place'
FAMILIES = (FAMILY,)
LIMIT = 12
HOISTS = 2  # constant stores the named dividend is also offered above
LOCAL = 'repair_dividend'
OPERATION = re.compile(r'\)\s*(?P<op>[%/])(?![=/*])\s*(?P<k>' + NUMBER + r')(?![\w.])')
PURE_MACROS = {'M2C_FIELD', 'sizeof'}
BLOCK_HEADS = re.compile(r'(?:if|for|while|do|else|switch|case|default)\b|' + IDENT + r'\s*:(?!:)')


def _opening_of(clean, close, lo):
    """The `(` that `clean[close]` (a `)`) closes, or None."""
    depth = 0
    for at in range(close, lo, -1):
        depth += (clean[at] == ')') - (clean[at] == '(')
        if depth == 0:
            return at
    return None


def _statements(part):
    """(start, end) of every `...;` statement of the body: start past blanks, end past the `;`."""
    clean, out, depth, start = part.clean, [], 0, part.opening + 1
    for at in range(part.opening + 1, part.end - 1):
        char = clean[at]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and char in ';{}':
            if char == ';':
                first = start
                while clean[first].isspace():
                    first += 1
                out.append((first, at + 1))
            start = at + 1
    return out


def _pure(text):
    calls = set(re.findall('(' + IDENT + r')\s*\(', text)) - PURE_MACROS
    return (not calls and not re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\.\d|\d\.|\b(?:f32|f64|float|double)\b', text))


def _fields(text):
    """The members a piece of C names: `->name`, `.name` and M2C_FIELD offsets."""
    offsets = re.findall(r'M2C_FIELD\s*\([^;]*?,\s*(' + NUMBER + r')\s*\)', text)
    return {int(o.rstrip('uUlL'), 0) for o in offsets} | set(re.findall(r'(?:->|\.)\s*(' + IDENT + ')', text))


def _constant_store(text):
    """The members a `member = literal;` statement writes, or None when it is anything else."""
    hit = re.fullmatch(r'(?P<left>[^=;{}]+?)\s*=\s*-?' + NUMBER + r'\s*;', text)
    if not hit or not re.search(r'->|\.|M2C_FIELD', hit['left']) or not _pure(hit['left']):
        return None
    return _fields(hit['left'])


def _indent(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return line if not line.strip() else ''


def variants(source, name):
    part = view(source, name)
    if not part or LOCAL in part.clean:
        return []
    clean, out = part.clean, []
    statements = _statements(part)
    local_names = {d['name'] for d in locals_for(part)}
    unsigned = set(re.findall(r'\b(?:u32|unsigned(?:\s+int)?)\s+(' + IDENT + ')', clean))
    for hit in OPERATION.finditer(clean, part.opening + 1, part.end):
        close = hit.start()
        opening = _opening_of(clean, close, part.opening)
        before = clean[max(part.opening, opening - 40):opening].rstrip() if opening is not None else ''
        if opening is None or before[-1:] == ')' or re.search(r'(?<!\w)(?!return$)\w+$', before):
            continue  # a call's or a cast operand's parenthesis
        inner = clean[opening + 1:close].strip()
        if not re.search(r'[\w)\]]\s*(?:\+|-(?!>))', inner) or not _pure(inner):
            continue
        at = next((i for i, (first, end) in enumerate(statements) if first <= opening < end), None)
        if at is None:
            continue
        first, end = statements[at]
        if BLOCK_HEADS.match(clean, first):
            continue
        dividend = source[opening + 1:close].strip()
        op, k = hit['op'], hit['k']
        pad = _indent(source, first)
        gap = '\n' + pad if pad else ' '
        whole = re.fullmatch(r'(' + IDENT + r')\s*=\s*', clean[first:opening])
        if whole and whole[1] in local_names and clean[hit.end():end].strip() == ';':
            out.append((FAMILY, edit(source, [(first, end, f'{whole[1]} = {dividend};{gap}{whole[1]} {op}= {k};')])))
            continue
        kind = 'u32' if unsigned & set(re.findall(IDENT, inner)) else 's32'
        declaration = (part.opening + 1, part.opening + 1, f'\n    {kind} {LOCAL};')
        lines = f'{LOCAL} = {dividend};{gap}{LOCAL} {op}= {k};{gap}'
        spots, read = [first], _fields(inner)
        for earlier in range(at - 1, max(-1, at - 1 - HOISTS), -1):
            start, stop = statements[earlier]
            written = _constant_store(clean[start:stop])
            if written is None or written & read or clean[stop:spots[-1]].strip():
                break
            spots.append(start)
        for spot in spots:
            out.append((FAMILY, edit(source, [declaration, (spot, spot, lines), (opening, hit.end(), LOCAL)])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
