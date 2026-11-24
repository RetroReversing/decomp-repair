"""A call's result that later arms overwrite with smaller candidates, kept apart from the minimum they compute.

A nearest-of-three choice

    d0 = dist(a, p); d1 = dist(b, p); d2 = dist(c, p);
    best = d0;
    if ((d1 < d0) && (d1 < d2)) { ...; best = d1; } else if ((d2 < d0) && (d1 > d2)) { ...; best = d2; }
    if (best < LIMIT) ...

comes back from m2c with `best` and `d0` as one variable (`d0 = d1;` in the arms, `if (d0 < LIMIT)`): one pseudo set
three times, live across the later calls, which global.c ranks below the other distances and gives the second saved
float register. With the copy written out, `d0` is set once and the minimum is a short-lived local of its own: the
target's `$f20`/`$f22` order. A 1928-instruction collision sweep (KMC gcc 2.7.2), four such blocks: one block alone
12008 -> 11768, all four 9918. One function; the judge decides.

The shape: `v = CALL(..);`, then statements that are calls, plain loads or copies, then a block where `v` is assigned
(`v = w;`) only inside braces, ending with `if (v < K)`. Children: every such variable at once, then each alone.
"""
import re

from .csource import _blank, find

FAMILY = 'minimum_result_copy'
COMBINED = 'minimum_result_copy_all'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'


def _sites(lines):
    """(variable, first line, insert line, last line) for each candidate."""
    out = []
    for i, line in enumerate(lines):
        m = re.match(r'[ \t]*(' + I + r')\s*=\s*' + I + r'\s*\(.*\)\s*;\s*$', line)
        if not m:
            continue
        v = m[1]
        k = i + 1
        while k < len(lines) and re.match(r'[ \t]*(?:(?:' + I + r'\s*=\s*)?' + I + r'\s*\(.*\)|[\w*().&>\- ]+\s*=\s*[^;]+)\s*;\s*$',
                                          lines[k]) and not re.search(r'\b' + v + r'\b', lines[k]):
            k += 1
        insert = k
        last = None
        sets_inside = 0
        depth = 0
        for j in range(k, min(k + 80, len(lines))):
            depth += lines[j].count('{') - lines[j].count('}')
            if depth < 0:
                break
            if re.match(r'\s*' + v + r'\s*=(?!=)', lines[j]):
                if depth == 0:
                    break
                sets_inside += 1
            if depth == 0 and re.match(r'\s*if \(' + v + r' < ', lines[j]):
                last = j
                break
        if last is not None and sets_inside:
            out.append((v, i, insert, last))
    return out


def _apply(lines, sites, names):
    lines = list(lines)
    decls = []
    for v, first, insert, last in sorted(sites, key=lambda s: s[1], reverse=True):
        b = 'best_' + v
        while b in names:
            b += '_'
        names.add(b)
        for j in range(insert, last + 1):
            lines[j] = re.sub(r'^(\s*)' + v + r'(\s*=(?!=))', r'\1' + b + r'\2', lines[j])
        lines[last] = lines[last].replace('if (' + v + ' < ', 'if (' + b + ' < ', 1)
        indent = re.match(r'[ \t]*', lines[insert])[0]
        lines.insert(insert, '%s%s = %s;' % (indent, b, v))
        decls.append((v, b))
    return lines, decls


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    body = source[opening:span[1]]
    lines = body.split('\n')
    sites = _sites(lines)
    if not sites:
        return []
    names = set(re.findall(I, clean))

    def build(chosen):
        new, decls = _apply(lines, chosen, set(names))
        text = '\n'.join(new)
        for v, b in decls:
            decl = re.search(r'(?m)^([ \t]*)((?:register\s+)?(?:f32|float|f64|double|s32|int))\s+' + v + r'\s*;', text)
            if not decl:
                return None
            text = text[:decl.end()] + '\n%s%s %s;' % (decl[1], decl[2], b) + text[decl.end():]
        return source[:opening] + text + source[span[1]:]
    out = []
    if len(sites) > 1:
        out.append((COMBINED, build(sites)))
    out += [(FAMILY, build([s])) for s in sites[:6]]
    return [(f, t) for f, t in out if t]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
