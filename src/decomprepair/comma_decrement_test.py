"""m2c's `t = X; n = t - 1; if ((t < 0) || (X = n, (n < 0)))`, back as `if ((X < 0) || (--X < 0))`.

A C `--X` inside a short-circuit condition loads X once, tests it, and in the other branch's delay slots counts it down
and stores it; m2c writes the load and the difference as locals of their own and the store as a comma operand of the
second test. The locals are global pseudos where the original had none, which on a 92-instruction N64 object update
(SN64 GCC 2.8.1, `-G0 -mips3 -O2`) left 15 points of a near-match; writing the decrement was exact (15 -> 0).

Shape: `t = X;`, `n = t - 1;` (or `+ 1`), then an `if` whose condition is `(t OP K) || (X = n, (n OP K2))` (or `&&`),
with `t` and `n` named nowhere else. X is an lvalue without calls or `++`/`--`. One child per site; the judge decides."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'comma_decrement_test'
FAMILIES = (FAMILY,)
LIMIT = 8
_STAGE = re.compile(rf'(?m)^([ \t]*)(?P<old>{IDENT})\s*=(?!=)\s*(?P<lv>[^;{{}}=]+?)\s*;\s*'
                    rf'(?P<new>{IDENT})\s*=(?!=)\s*(?P=old)\s*(?P<sign>[-+])\s*1\s*;\s*(?=if\s*\()')
_UNSAFE = re.compile(rf'\+\+|--|\b(?!M2C_FIELD\b){IDENT}\s*\(')
_CONDITION = r'\s*\(?\s*{old}\s*(?P<op1>[<>]=?|[!=]=)\s*(?P<k1>-?\w+)\s*\)?\s*(?P<join>\|\||&&)\s*\(\s*{lv}\s*=\s*{new}\s*,' \
             r'\s*\(?\s*{new}\s*(?P<op2>[<>]=?|[!=]=)\s*(?P<k2>-?\w+)\s*\)?\s*\)\s*'


def _spaced(text):
    """A regex of `text` that ignores how it is spaced."""
    return r'\s*'.join(re.escape(token) for token in re.findall(r'\w+|[^\w\s]', text))


def _site(clean, hit):
    start = clean.index('(', hit.end())
    stop = close(clean, start, '(', ')')
    if not stop:
        return None
    old, new, lv = hit['old'], hit['new'], hit['lv'].strip()
    if old == new or _UNSAFE.search(lv) or not re.search(r'\*|->|\.|\[|M2C_FIELD', lv):
        return None
    pattern = _CONDITION.format(old=old, new=new, lv=_spaced(lv))
    found = re.fullmatch(pattern, clean[start + 1:stop - 1])
    return (start + 1, stop - 1, found) if found else None


def variants(source, name):
    part = view(source, name)
    if not part or '||' not in part.body and '&&' not in part.body:
        return []
    clean = part.clean
    out = []
    for hit in _STAGE.finditer(clean, part.opening, part.end):
        site = _site(clean, hit)
        if not site:
            continue
        start, stop, found = site
        old, new = hit['old'], hit['new']
        # `t` and `n` are named in their declarations, the two statements and the condition only
        elsewhere = clean[part.opening:hit.start()] + clean[stop:part.end]
        elsewhere = re.sub(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?[ \t*](?:{old}|{new})[ \t]*;', '', elsewhere)
        if re.search(rf'\b(?:{old}|{new})\b', elsewhere):
            continue
        # the source's own spelling of X (the blanked text drops nothing outside comments and strings)
        lv = source[hit.start('lv'):hit.end('lv')].strip()
        step = '--' if hit['sign'] == '-' else '++'
        condition = (f'({lv} {found["op1"]} {found["k1"]}) {found["join"]} '
                     f'({step}{lv} {found["op2"]} {found["k2"]})')
        out.append((FAMILY, edit(source, [(hit.start('old'), hit.end(), ''), (start, stop, condition)])))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
