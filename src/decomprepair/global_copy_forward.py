"""A local copy of a value stored to a global, read back from the global in the loop that uses it.

m2c names every value it reads: `s0 = G + 1; G = s0; stamp = s0; for (...) { if (p->f != stamp) p->f = stamp; }`.
The game wrote `G++;` (or `G = G + 1;`) and read `G` in the loop. For GCC 2.x that is not the same code even when
the instructions come out equal: the loop's reads of `G` are loop-invariant memory loads, loop.c hoists them to the
preheader *after* the loop's entry test, and cse hands them the value just stored, so the copy that feeds the loop
(`move $t2, $v0`) sits after the `beqz` of the entry test, next to the other hoisted copies. A local copy written
before the loop is a plain register copy in the block before that test instead, which the scheduler and the delay
slot filler then place differently (a KMC gcc 2.7.2 near miss, score 60 with the copy before the test: the copy
filled the test's delay slot and the loop counter's `move $t0, $zero` was hoisted above the increment; reading the
global in the loop made it exact).

The shape, all of it required: `G = T;` (G an extern scalar global, T a local) and later `L = T;` for a local `L`
that is written nowhere else and read only after that line; then no other write to `G` (no `G = ..`, `G++`, `&G`)
and no call after the store, so reading `G` instead of `L` cannot see another value. The rewrite deletes `L = T;`,
reads `G` wherever `L` was read, and drops `L`'s declaration. One variant per copy, and one with all of them.
"""
import re

from .csource import _blank, find

FAMILY = 'global_copy_forward'
FAMILIES = (FAMILY,)
ID = r'[A-Za-z_]\w*'
CALL = re.compile(rf'(?<![\w.>])(?!sizeof\b|if\b|while\b|for\b|switch\b|return\b){ID}\s*\(')


def _python_body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    depth = 0
    for i in range(opening, span[1]):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth == 0:
            return opening, i + 1, clean
    return None


_body = _python_body
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _body(source, name):
        span = find(source, name)
        if not span:
            return None
        clean = _blank(source)
        opening = clean.find('{', span[0], span[1])
        if opening < 0:
            return None
        found = _scan.close_every(clean, opening, '{', '}', True, None)
        if found is NotImplemented or span[1] > len(clean):
            return _python_body(source, name)
        return (opening, found, clean) if found is not None and found <= span[1] else None


def _writes(line, name):
    return bool(re.search(rf'(?<![\w.>])\s*{name}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)', line)
                or re.search(rf'(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)', line))


def variants(source, name):
    part = _body(source, name)
    if not part:
        return []
    opening, end, clean = part
    types = {m['g']: m['type'].strip() for m in re.finditer(
        rf'(?m)^[ \t]*extern\s+(?P<type>[\w ]+?)\s+(?P<g>{ID})\s*;', clean[:opening])}
    if not types:
        return []
    head, body, tail = source[:opening + 1], source[opening + 1:end - 1], source[end - 1:]
    lines = body.split('\n')
    text = [re.sub(r'//.*|/\*.*?\*/', '', line) for line in clean[opening + 1:end - 1].split('\n')]
    options = []
    for s, line in enumerate(text):
        store = re.fullmatch(rf'\s*({ID})\s*=\s*({ID})\s*;\s*', line)
        if not store or store[1] not in types or store[2] in types:
            continue
        glob, temp = store[1], store[2]
        after = '\n'.join(text[s + 1:])
        if CALL.search(after) or re.search(rf'&\s*{glob}\b', body) or any(
                _writes(other, glob) for i, other in enumerate(text) if i != s):
            continue
        for c in range(s + 1, len(text)):
            copy = re.fullmatch(rf'\s*({ID})\s*=\s*{temp}\s*;\s*', text[c])
            if not copy or copy[1] in types or copy[1] == temp:
                continue
            local = copy[1]
            if any(_writes(text[i], temp) for i in range(s + 1, c)):
                continue
            if sum(_writes(other, local) for other in text) != 1 or re.search(rf'&\s*{local}\b', body):
                continue
            used = [i for i, other in enumerate(text) if re.search(rf'(?<![\w.>]){local}\b', other)]
            decls = [i for i in used if re.fullmatch(rf'\s*[\w ]+\s+\*?{local}\s*;\s*', text[i])]
            if any(i < c and i not in decls for i in used) or not any(i > c for i in used):
                continue
            options.append((glob, local, c, decls))
    if not options:
        return []

    def rewrite(chosen):
        out = list(lines)
        for glob, local, c, decls in chosen:
            for i in range(c + 1, len(out)):
                if out[i] is not None:
                    out[i] = re.sub(rf'(?<![\w.>]){local}\b', glob, out[i])
            out[c] = None
            for i in decls:
                out[i] = None
        return head + '\n'.join(line for line in out if line is not None) + tail

    result = [(FAMILY, rewrite([o])) for o in options]
    if len(options) > 1:
        result.append((FAMILY, rewrite(options)))
    return result[:6]
