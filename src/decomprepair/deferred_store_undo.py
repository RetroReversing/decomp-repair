"""Values computed into temporaries and then stored in the same order, written as the direct stores again.

`deferred_stores` (deferred_store_repairs) offers `a = E0; b = E1; p[0] = a; p[1] = b;` for a vector updated in place;
a search can keep that child where the stores do not alias their operands, and the extra pseudos then move the
registers around them. The reverse: a run of `t_k = E_k;` followed directly by `X_k = t_k;` in the same order, each `t_k`
used nowhere else, becomes `X_k = E_k;`. A 1928-instruction collision sweep (KMC gcc 2.7.2), one such run on an
out-parameter: 6988 -> 6893. Children: every run at once, then each.
"""
import re

from .csource import _blank, find

FAMILY = 'deferred_store_undo'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
ASSIGN = re.compile(r'[ \t]*(' + I + r') = ([^;]+);\s*$')
STORE = re.compile(r'([ \t]*)([^=;]+?) = (' + I + r');\s*$')


def _runs(lines, clean):
    out = []
    i = 0
    while i < len(lines):
        temps = []
        k = i
        while k < len(lines) and ASSIGN.match(lines[k]):
            temps.append((k, ASSIGN.match(lines[k])))
            k += 1
        n = len(temps)
        ok = n >= 2 and k + n <= len(lines)
        stores = []
        for j in range(n if ok else 0):
            m = STORE.match(lines[k + j])
            t = temps[j][1][1]
            if not m or m[3] != t or len(re.findall(r'(?<![\w.>])' + t + r'\b', clean)) != 3:
                ok = False
                break
            stores.append(m)
        if ok:
            out.append((i, n, [t[1] for t in temps], stores))
            i = k + n
        else:
            i += 1
    return out


def _apply(lines, runs):
    lines = list(lines)
    names = []
    for i, n, temps, stores in sorted(runs, key=lambda r: r[0], reverse=True):
        new = ['%s%s = %s;' % (s[1], s[2].strip(), t[2].strip()) for t, s in zip(temps, stores)]
        lines[i:i + 2 * n] = new
        names += [t[1] for t in temps]
    text = '\n'.join(lines)
    for t in names:
        text = re.sub(r'(?m)^[ \t]*(?:register\s+)?[\w ]+?\s\**' + re.escape(t) + r'\s*;\n', '', text, count=1)
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    lines = source[opening:span[1]].split('\n')
    runs = _runs(lines, clean[opening:span[1]])
    if not runs:
        return []
    wrap = lambda text: source[:opening] + text + source[span[1]:]  # noqa: E731
    out = [(FAMILY, wrap(_apply(lines, runs)))] if len(runs) > 1 else []
    return out + [(FAMILY, wrap(_apply(lines, [r]))) for r in runs[:6]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
