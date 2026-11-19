"""A global that an empty loop waits on, declared volatile as the game's own declaration was.

m2c writes a busy wait on a flag another thread or an interrupt sets as an empty loop:

    do {

    } while (D_800E4214 != 0);

Without `volatile` gcc reads the global once and tests that value forever, so the loop is a single branch to
itself; the game reloads the global on every turn. An N64 function with two such waits was 96.1% (once its
leftover scaffolding was taken out) and exact with both globals `volatile`. Offered for globals an empty loop's
condition reads and the loop's body doesn't write (it has none): each alone, and all of them together.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'busy_wait_volatile'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
# `do { } while (C);` and `while (C) { }` / `while (C);` with nothing in the body
EMPTY_DO = re.compile(r'\bdo\s*\{\s*\}\s*while\s*\(')


def _closes_do(clean, at):
    """Whether the code just before `at` is the `}` of a `do { … }` block."""
    before = clean[:at].rstrip()
    if not before.endswith('}'):
        return False
    depth = 0
    for i in range(len(before) - 1, -1, -1):
        depth += (before[i] == '}') - (before[i] == '{')
        if depth == 0:
            return bool(re.search(r'\bdo\s*$', clean[:i]))
    return False


def _conditions(clean, opening, end):
    for hit in EMPTY_DO.finditer(clean, opening, end):
        paren = hit.end() - 1
        closing = close(clean, paren)
        if closing:
            yield clean[paren + 1:closing - 1]
    for hit in re.finditer(r'\bwhile\s*\(', clean[opening:end]):
        start = opening + hit.start()
        if _closes_do(clean, start):  # the tail of a do/while, handled above
            continue
        paren = opening + hit.end() - 1
        closing = close(clean, paren)
        if closing and re.match(r'\s*(?:;|\{\s*\})', clean[closing:end]):
            yield clean[paren + 1:closing - 1]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    declared = {m['name']: m for m in re.finditer(
        r'(?m)^[ \t]*extern\s+(?P<type>(?:(?:unsigned|signed|const)\s+)*' + IDENT + r')\s+(?P<name>' + IDENT
        + r')\s*;', outside)}
    waited = []
    for condition in _conditions(clean, opening, end):
        for symbol in re.findall(r'(?<![\w.>])(' + IDENT + r')\b', condition):
            if symbol in declared and symbol not in waited and 'volatile' not in declared[symbol].group(0):
                waited.append(symbol)
    if not waited:
        return []

    def make(symbols):
        text = source
        for symbol in symbols:
            line = declared[symbol].group(0).strip()
            text = text.replace(line, line.replace('extern ', 'extern volatile ', 1), 1)
        return text
    result = []
    for choice in ([waited] if len(waited) > 1 else []) + [[s] for s in waited]:
        text = make(choice)
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result[:4]
