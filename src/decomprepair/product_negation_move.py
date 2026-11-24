"""Where the negation of a product by a constant sits: `e * -K`, `(-e) * K` or `-(e * K)`.

Observed (SN/KMC GCC 2.7.2 `-G0 -O2`; one function, a 21-instruction setter that adds a scaled global to a float
field; 85 -> 0): m2c writes a product by a negative constant,

    t = field + (f32) (g * -0x14);         /* draft: the shift-and-add chain runs first, `negu` last */
    t = field + (f32) (-g * 0x14);         /* target: `negu` right after the load, then the chain on the negation */

All three spellings are the same integer value, but each is a different tree. The multiply expander turns `x * 20`
into shifts and adds of `x`, so the tree decides whether the negation is applied to the operand before that chain or to
the chain's result afterwards, and the order of the instructions (and the registers the chain's temporaries take)
follows. Hypothesis (not confirmed in the compiler's source): `expand_mult` is handed the operand as it is written, and
a negative constant takes its negate-the-result path, while a negated operand is an ordinary unary minus the scheduler
places by its uses.

Children: every product by a negative literal (`e * -K`, `e * (-K)`, `-K * e`), a negated operand times a literal
(`-e * K`, `(-e) * K`, `K * -e`) and a negated product (`-(e * K)`, `-(K * e)`) rewritten into each of the other two
spellings (`e * -K`, `(-e) * K`, `(-(e * K))`), one site at a time, then every site together per spelling. `e` is a
parenthesized group (with its cast) or a plain variable, member or element chain, with no call, assignment,
`++`/`--`, comparison or volatile name, and nothing declared float (negation and product round the same way only in
integers). `K` is an integer literal of at least 2; floating literals are left alone. Proposals only; the judge decides."""
import re

from decomprepair.product_split_sum import (
    _FLOAT_DECL,
    _NUM,
    _VOLATILE,
    _binds_alone,
    _group_end,
    _operand_after,
    _operand_before,
    _prev_char,
    _pure,
)

FAMILIES = ('product_negation_move',)
FAMILY = FAMILIES[0]
LIMIT = 12
_FLOAT_TOKEN = re.compile(r'\b(?:f32|f64|float|double)\b|\d\.\d|\d[fF]\b')
_AFTER_LITERAL_BAD = re.compile(r'\s*(?:[.(\[\w]|\*=)')
_UNARY_OK = set('(,=<>?:[{;}|^!~') | {''}  # what may precede a minus that is unary and starts our span
_SPELLINGS = ('mul_neg', 'neg_mul', 'neg_prod')  # e * -K, (-e) * K, (-(e * K))


def _mask(source):
    """The source with comments and preprocessor lines blanked (same length), the text the scanner reads."""
    def blank(m):
        return re.sub(r'[^\n]', ' ', m[0])
    text = re.sub(r'/\*.*?\*/|//[^\n]*', blank, source, flags=re.S)
    return re.sub(r'(?m)^[ \t]*#(?:[^\n\\]|\\\n)*', blank, text)


def _skip(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _unary_before(text, i):
    """The index of a unary minus that ends just before `i` (skipping blanks), or None."""
    char, j = _prev_char(text, i)
    if char != '-':
        return None
    before, _ = _prev_char(text, j)
    return j if before in _UNARY_OK else None


def _whole_operand(text):
    """True when `text` (stripped) is exactly one operand: a cast group, a parenthesized group or a chain."""
    text = text.strip()
    span = _operand_after(text, 0)
    return bool(text) and span is not None and span[0] == 0 and span[1] == len(text) and not text.startswith('-')


def _factor(text):
    return int(text, 0) >= 2


def _literal_ok(text, end):
    return not _AFTER_LITERAL_BAD.match(text, end)


def _group_inner(text, open_):
    end = _group_end(text, open_)
    return (text[open_ + 1:end - 1], end) if end else (None, None)


def _neg_literal_before(text, star):
    """(start, K) of `-K` or `(-K)` ending just before the `*` at `star`, or None."""
    _, i = _prev_char(text, star)
    if i < 0:
        return None
    closing = text[i] == ')'
    head = text[:i] if closing else text[:i + 1]
    m = re.search(r'(' + (r'\(\s*' if closing else '') + r')-\s*(' + _NUM + r')\s*$', head)
    if not m or not _factor(m[2]):
        return None
    if closing:
        start = m.start()
    else:
        start = m.start() + len(m[1])  # the minus itself
        before, _ = _prev_char(text, start)
        if before not in _UNARY_OK:
            return None
    if re.search(r'[A-Za-z_]\w*\s*$', text[:start]) and not re.search(r'\breturn\s*$', text[:start]):
        return None
    return start, m[2]


def _neg_literal_after(text, index):
    """(end, K) of `-K` or `(-K)` starting after `index`, or None."""
    i = _skip(text, index)
    paren = i < len(text) and text[i] == '('
    m = re.compile(r'\(\s*-\s*(' + _NUM + r')\s*\)' if paren else r'-\s*(' + _NUM + r')(?![\w.])').match(text, i)
    if not m or not _factor(m[1]):
        return None
    return (m.end(), m[1]) if _literal_ok(text, m.end()) else None


def _find(text, floats, volatiles):
    """Sites: (start, end, operand, K, own spelling), each a product with a negation somewhere in it."""
    found = {}

    def ok(operand):
        stripped = operand.strip()
        inner = stripped[1:].lstrip() if stripped.startswith('(') else stripped
        return (not inner.startswith('-') and not _FLOAT_TOKEN.search(operand) and _pure(operand, floats, volatiles))

    def add(a, b, operand, k, own):
        if ok(operand):
            found.setdefault((a, b), (a, b, operand.strip(), k, own))

    for m in re.finditer(r'(?<![*=/<>&|^+\-%!])\*(?![*=])', text):
        star = m.start()
        # e * -K, e * (-K)
        after = _neg_literal_after(text, star + 1)
        span = _operand_before(text, star)
        if after and span and _binds_alone(text, span[0]) and not _unary_before(text, span[0]):
            add(span[0], after[0], text[span[0]:span[1]], after[1], 'mul_neg')
        # -K * e, (-K) * e
        lit = _neg_literal_before(text, star)
        right = _operand_after(text, star + 1)
        if lit and right and not re.match(r'\s*[.(\[]', text[right[1]:]):
            start = lit[0]
            if text[start] == '(' and not _binds_alone(text, start):
                pass
            else:
                add(start, right[1], text[right[0]:right[1]], lit[1], 'mul_neg')
        # (-e) * K, -e * K
        number = _NUM
        lit_after = re.compile(r'\s*(' + number + r')(?![\w.])').match(text, star + 1)
        if lit_after and _factor(lit_after[1]) and _literal_ok(text, lit_after.end()):
            span = _operand_before(text, star)
            if span:
                start, end = span
                if text[end - 1] == ')' and text[start] == '(':
                    inner = text[start + 1:end - 1]
                    if inner.lstrip().startswith('-') and _whole_operand(inner.lstrip()[1:]) and _binds_alone(text, start):
                        add(start, lit_after.end(), inner.lstrip()[1:], lit_after[1], 'neg_mul')
                minus = _unary_before(text, start)
                if minus is not None and _binds_alone(text, minus + 1):
                    add(minus, lit_after.end(), text[start:end], lit_after[1], 'neg_mul')
        # K * (-e), K * -e
        char, i = _prev_char(text, star)
        number_before = re.search(r'(?<![\w.])(' + _NUM + r')$', text[:i + 1]) if char.isalnum() else None
        if number_before and _factor(number_before[1]) and _binds_alone(text, number_before.start()):
            j = _skip(text, star + 1)
            if j < len(text) and text[j] == '(':
                inner, end = _group_inner(text, j)
                if inner is not None and inner.lstrip().startswith('-') and _whole_operand(inner.lstrip()[1:]):
                    add(number_before.start(), end, inner.lstrip()[1:], number_before[1], 'neg_mul')
            elif j < len(text) and text[j] == '-' and text[j + 1:j + 2] != '-':
                right = _operand_after(text, j + 1)
                if right and not re.match(r'\s*[.(\[]', text[right[1]:]):
                    add(number_before.start(), right[1], text[right[0]:right[1]], number_before[1], 'neg_mul')
    # -(e * K), -(K * e)
    for m in re.finditer(r'-\s*\(', text):
        minus = m.start()
        if _prev_char(text, minus)[0] not in _UNARY_OK or text[minus - 1:minus] == '-':
            continue
        open_ = m.end() - 1
        inner, end = _group_inner(text, open_)
        if inner is None or re.match(r'\s*[.\[]', text[end:]):
            continue
        depth, stars = 0, []
        for n, c in enumerate(inner):
            depth += (c == '(') - (c == ')')
            if c == '*' and depth == 0 and inner[n - 1:n] != '*' and inner[n + 1:n + 2] not in ('*', '='):
                stars.append(n)
        if len(stars) != 1:
            continue
        left, right = inner[:stars[0]].strip(), inner[stars[0] + 1:].strip()
        for operand, literal in ((left, right), (right, left)):
            if re.fullmatch(_NUM, literal) and _factor(literal) and _whole_operand(operand):
                add(minus, end, operand, literal, 'neg_prod')
                break
    return sorted(found.values())


def _spell(kind, operand, k):
    if kind == 'mul_neg':
        return f'{operand} * -{k}'
    neg = f'({operand})' if operand.startswith('-') else operand
    if kind == 'neg_mul':
        return f'(-{neg}) * {k}'
    return f'(-({operand} * {k}))'


def variants(source, name=None, header=None):
    text = _mask(source)
    floats = set(_FLOAT_DECL.findall((header or '') + '\n' + text))
    volatiles = set(_VOLATILE.findall((header or '') + '\n' + text))
    sites = _find(text, floats, volatiles)
    sites = [s for s in sites if not any(o is not s and o[0] <= s[0] and s[1] <= o[1] for o in sites)]
    if not sites:
        return []

    def apply(chosen, kind):
        out = source
        for a, b, operand, k, own in sorted(chosen, reverse=True):
            out = out[:a] + _spell(kind, operand, k) + out[b:]
        return out

    kids = []
    for kind in _SPELLINGS:
        changed = [s for s in sites if s[4] != kind]
        kids += [apply([s], kind) for s in changed]
        if len(changed) > 1:
            kids.append(apply(changed, kind))
    unique = list(dict.fromkeys(kids))
    return [(FAMILY, s) for s in unique if s != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
