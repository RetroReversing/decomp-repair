"""A product `e * N` by a small constant written as the sum `e + (e * (N - 1))`: the add's operand order follows.

Observed (KMC GCC 2.7.2, `-G0 -O2`; one function, a 20-instruction setter): a quotient scaled and offset,

    t = (((a - 0x12) / 10) * 0xD) + 0x12;                              /* draft: addu $a1, $v0, $v1 */
    t = ((a - 0x12) / 10) + (((a - 0x12) / 10) * 0xC) + 0x12;          /* target: addu $a1, $v1, $v0 */

Both are 13q + 0x12. The compiler turns `q * 13` into a shift-and-add chain (or `mult`) whose final add takes the
quotient and the product in an order that follows the tree it was given; the sum spelling puts the quotient first and
the product second, which is the order the target has. Caching the quotient in a local was worse (the compiler then
shares one register between both terms); the expression has to be recomputed in each term, so it must be free of side
effects. Hypothesis (not confirmed in the compiler's source): the multiply expander (`expand_mult`) and the plus tree
keep operand order from the tree, so the choice is made by the C.

Children: each `e * N` or `N * e` (N an integer literal, 2..64) as `(e + (e * N-1))` and as `((e * N-1) + e)`, one site
at a time, then every site together in the first form. `e` is a parenthesized group (with its cast) or a plain
variable, member or element chain, with no call, assignment, `++`/`--`, comparison or volatile name, and no name or
field declared as a float (3x and x + 2x round differently there). `e` is at most 120 characters. The product keeps
its place in the tree: the new sum is parenthesized, so nothing else in the statement regroups.
Proposals only; the judge decides."""
import re

FAMILIES = ('product_split_sum',)
FAMILY = FAMILIES[0]
LIMIT = 16
MAX_FACTOR = 64
MAX_OPERAND = 120

_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_TYPES = r'(?:[us](?:8|16|32|64)|int|short|char|long|unsigned|signed|f32|f64|float|double)'
_CAST_BEFORE = re.compile(r'\(\s*' + _TYPES + r'(?:\s+' + _TYPES + r')*(?:\s*\*+)?\s*\)\s*$')
_CHAIN = re.compile(r'[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*|\s*\[[^\[\]]*\])*')
_FLOAT_DECL = re.compile(r'\b(?:f32|f64|float|double)\s+\**\s*([A-Za-z_]\w*)')
_VOLATILE = re.compile(r'\bvolatile\b[^;{}]*?\b([A-Za-z_]\w*)\s*(?:[;,=\[)]|$)')
_IMPURE = re.compile(r'\+\+|--|[A-Za-z_]\w*\s*\(|[=<>!?,]|&&|\|\||\bsizeof\b|\bvolatile\b|\d\.\d|\d[fF]\b')
_AFTER_LITERAL_BAD = re.compile(r'\s*(?:[.(\[\w]|\*=)')
_BEFORE_OK = set('(,=+-<>?:[{;}|^!~') | {''}  # not * / % (same precedence), & (unary), ) or a name


def _group_start(text, close):
    """The index of the `(` matching the `)` at `close`, or None."""
    depth = 0
    for i in range(close, -1, -1):
        if text[i] == ')':
            depth += 1
        elif text[i] == '(':
            depth -= 1
            if depth == 0:
                return i
    return None


def _group_end(text, open_):
    depth = 0
    for i in range(open_, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _prev_char(text, index):
    """(char, index) of the last non-blank character before `index`."""
    i = index - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    return (text[i], i) if i >= 0 else ('', -1)


def _binds_alone(text, start):
    """True when the operand starting at `start` is not the right side of a same-precedence or unary operator."""
    char, i = _prev_char(text, start)
    if char in ('-', '+') and i > 0 and text[i - 1] == char:
        return False
    if char == '&':
        return False
    if char == ')' or char.isalnum() or char == '_':
        word = re.search(r'([A-Za-z_]\w*)\s*$', text[:i + 1])
        return bool(word) and word[1] == 'return' and char != ')'
    return char in _BEFORE_OK


def _operand_before(text, star):
    """(start, end) of the operand to the left of the `*` at `star`, or None."""
    char, i = _prev_char(text, star)
    if char == ')':
        open_ = _group_start(text, i)
        if open_ is None:
            return None
        head = text[:open_]
        if re.search(r'[A-Za-z_]\w*\s*$', head):
            return None  # a call or a keyword's condition
        cast = _CAST_BEFORE.search(head)
        start = cast.start() if cast else open_
        return (start, i + 1) if _binds_alone(text, start) else None
    if char == ']' or char.isalnum() or char == '_':
        for m in _CHAIN.finditer(text[:i + 1]):
            if m.end() == i + 1 and (m.start() == 0 or not (text[m.start() - 1].isalnum() or text[m.start() - 1] in '_.>')):
                return (m.start(), i + 1) if _binds_alone(text, m.start()) else None
    return None


def _operand_after(text, index):
    """(start, end) of the operand to the right of `index`, or None."""
    i = index
    while i < len(text) and text[i].isspace():
        i += 1
    cast = re.compile(r'\(\s*' + _TYPES + r'(?:\s+' + _TYPES + r')*(?:\s*\*+)?\s*\)\s*').match(text, i)
    j = cast.end() if cast else i
    if j < len(text) and text[j] == '(':
        end = _group_end(text, j)
        return (i, end) if end else None
    if cast:
        return None
    m = _CHAIN.match(text, i)
    return (m.start(), m.end()) if m else None


def _pure(operand, floats, volatiles):
    plain = re.sub(r'\([su](?:8|16|32|64)\)|\(int\)', '', operand).replace('->', '.')
    if len(operand) > MAX_OPERAND or _IMPURE.search(re.sub(r'<<|>>', ' ', plain)):
        return False
    return not {w for w in re.findall(r'[A-Za-z_]\w*', operand)} & (floats | volatiles)


def _sites(source, header):
    text = source
    floats = set(_FLOAT_DECL.findall((header or '') + '\n' + text))
    volatiles = set(_VOLATILE.findall((header or '') + '\n' + text))
    for m in re.finditer(r'(?<![*=/<>&|^+\-%!])\*(?![*=])', text):
        star = m.start()
        # e * N
        lit = re.compile(r'\s*(' + _NUM + r')(?![\w.])').match(text, star + 1)
        if lit and not _AFTER_LITERAL_BAD.match(text, lit.end()):
            span = _operand_before(text, star)
            factor = int(lit[1], 0)
            if span and 2 <= factor <= MAX_FACTOR and _pure(text[span[0]:span[1]], floats, volatiles):
                yield span[0], lit.end(), text[span[0]:span[1]], lit[1]
                continue
        # N * e
        char, i = _prev_char(text, star)
        if char.isalnum():
            number = re.search(r'(?<![\w.])(' + _NUM + r')$', text[:i + 1])
            if number and 2 <= int(number[1], 0) <= MAX_FACTOR and _binds_alone(text, number.start()):
                after = _operand_after(text, star + 1)
                if after and _pure(text[after[0]:after[1]], floats, volatiles) and not re.match(r'\s*[.(\[]', text[after[1]:]):
                    yield number.start(), after[1], text[after[0]:after[1]], number[1]


def _spell(factor, like):
    less = int(factor, 0) - 1
    return hex(less).upper().replace('0X', '0x') if like.lower().startswith('0x') else str(less)


def variants(source, name=None, header=None):
    sites = []
    seen = set()
    for a, b, operand, factor in _sites(source, header):
        if (a, b) in seen:
            continue
        seen.add((a, b))
        rest = _spell(factor, factor)
        first, second = f'{operand} + ({operand} * {rest})', f'({operand} * {rest}) + {operand}'
        # already the whole content of a parenthesis (`(e * 13) + 1`): no second pair; or a call's argument or a
        # statement's value (`x = e * 13;`): the sum needs none either
        before, after = _prev_char(source, a)[0], source[b:].lstrip()[:1]
        bare = (before, after) in {('(', ')'), ('(', ','), (',', ')'), (',', ','), ('=', ';')}
        sites.append((a, b, first if bare else f'({first})', second if bare else f'({second})'))
    if not sites:
        return []
    def apply(chosen, which):
        text = source
        for a, b, *forms in sorted(chosen, reverse=True):
            text = text[:a] + forms[which] + text[b:]
        return text

    out = []
    for site in sites:
        out += [apply([site], 0), apply([site], 1)]
    flat = [s for s in sites if not any(o is not s and o[0] <= s[0] and s[1] <= o[1] for o in sites)]
    if len(flat) > 1:
        out.append(apply(flat, 0))
    unique = list(dict.fromkeys(out))
    return [(FAMILY, s) for s in unique if s != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
