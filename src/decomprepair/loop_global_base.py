"""A loop that reads a record pointer through the local that was stored to a global, reading the global itself instead.

An N64 map-table setup (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) stored `entries` to `D_800BFF04`, walked the
entries in one loop and again in a second. m2c wrote the first loop over the local (`entries`) and the second over the
global, and the original wrote both the same way: each pass reads the global into a loop-scoped local (`MapEntry *base
= D_800BFF04;`), tests that local first and forms the entry pointer through the one-argument cast helper the function
already carries (`inline_fn((i * 8) + (u8 *) base)`). Over the local the pointer is one pseudo from the store to the loop
and its register ties to the address load's; read again it is a copy created in the loop's preheader, which allocates
differently (the register hypothesis, from `cc1 -dl -dg` dumps, not confirmed in the compiler source). On its own the
rewrite scored the same as the m2c form (85 -> 85) and the struct member read of one field and a statement reorder
(`field_struct_view_printed`, `statement_group_order`) took it to 50 and then 0, so a search has to keep this neutral step.

Where a statement `G = P;` (P a pointer local, G a global) comes before a `for` or `while` loop with no call in its body
that never assigns P or G, the loop is offered with `T *base = G;` at the top of its body and P replaced by `base`;
and, when the source defines a one-argument cast helper `static T *h(u8 *a) { return (T *) a; }`, with each
`x = (T *) (... (u8 *) base);` in the body written `x = h(...)`. A candidate for the exact judge, never a verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_global_base'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
CALL = re.compile(r'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof)\b)' + IDENT + r'\s*\(')
KEYWORDS = {'return', 'else', 'goto', 'break', 'continue', 'case', 'default', 'do'}
LOOP_LIMIT = 4


def _helpers(clean):
    """{return type: helper name} for each `static T *h(u8 *a) { return (T *) a; }` in the source."""
    found = {}
    for m in re.finditer(r'(?:inline\s+static|static\s+inline|static)\s+(' + IDENT + r'(?:\s+' + IDENT + r')*)\s*\*\s*(' + IDENT +
                         r')\s*\(\s*u8\s*\*\s*(' + IDENT + r')\s*\)\s*\{\s*return\s*\(\s*\1\s*\*\s*\)\s*\3\s*;\s*\}', clean):
        found.setdefault(m[1], m[2])
    return found


def _inline_names(clean):
    """Names of the functions the source defines `static` (or `inline`): a loop may call them, they touch no global."""
    return set(re.findall(r'(?:inline|static)[\w \t*]*?[ \t*](' + IDENT + r')\s*\([^;{)]*\)\s*\{', clean))


def _pairs(body):
    """(P, G, T, end of the store) for each `G = P;` where P is a pointer local and G is not a local."""
    pairs = []
    for copy in re.finditer(r'(?<![\w.>])(' + IDENT + r')\s*=(?!=)\s*(' + IDENT + r')\s*;', body):
        g, p = copy.groups()
        decl = re.search(r'(?m)^[ \t]*(' + IDENT + r'(?:[ \t]+' + IDENT + r')*)[ \t]*\*[ \t]*' + p + r'[ \t]*;', body)
        if (g in KEYWORDS or p in KEYWORDS or not decl or re.search(r'(?m)^[ \t]*[\w ]+[ \t*]' + g + r'[ \t]*;', body)
                or any((p, g) == pair[:2] for pair in pairs)):
            continue
        pairs.append((p, g, decl[1], copy.end()))
    return pairs


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    helpers = _helpers(clean)
    pure = _inline_names(clean)
    result = []
    for p, g, kind, stored in _pairs(body):
        word = r'(?<![\w.>])' + p + r'\b'
        wrote = re.compile(r'(?<![\w.>])(?:' + p + '|' + g + r')\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + p + r'\b|\b' + p + r'\s*(?:\+\+|--)')
        for loop in re.finditer(r'(?<![\w.>])(for|while)\s*\(', clean[opening + stored:end]):
            head = opening + stored + loop.start()
            stop = close(clean, head + len(loop[0]) - 1, '(', ')')
            brace = re.match(r'\s*\{', clean[stop:end]) if stop else None
            if not brace:
                continue
            a = stop + brace.end()
            b = close(clean, a - 1, '{', '}')
            if not b:
                continue
            inner = clean[a:b - 1]
            calls = [c for c in CALL.finditer(inner) if c[0].rstrip('( \t\n').strip() not in pure]
            if calls or wrote.search(inner) or not re.search(word, inner):
                continue
            local = 'base'
            while re.search(r'\b' + local + r'\b', clean[opening:end]):
                local += '_'
            indent = re.match(r'\n([ \t]*)', source[a:]) or re.match(r'()', '')
            pad = indent[1] if indent else ''
            text = re.sub(word, local, source[a:b - 1])
            staged = source[:a] + f'\n{pad}{kind} *{local} = {g};' + text + source[b - 1:]
            offers = [staged]
            helper = helpers.get(kind)
            if helper:
                cast = re.compile(r'(' + IDENT + r')(\s*=\s*)\(\s*' + re.escape(kind) + r'\s*\*\s*\)\s*\((.*?)\);', re.S)

                def wrap(m, helper=helper, local=local):
                    cast_base = '(u8 *) ' + local in m[3] or '(u8 *)' + local in m[3]
                    return f'{m[1]}{m[2]}{helper}({m[3]});' if cast_base else m[0]
                changed = cast.sub(wrap, text)
                if changed != text:
                    offers.append(source[:a] + f'\n{pad}{kind} *{local} = {g};' + changed + source[b - 1:])
            for offer in offers:
                if (FAMILY, offer) not in result:
                    result.append((FAMILY, offer))
            if len(result) >= LOOP_LIMIT * 2:
                return result
    return result
