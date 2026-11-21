"""Three small rewrites from one KMC gcc 2.7.2 float-clamp function (an N64 collision-span mask), each a step of its
525 -> 0 match, each below the permuter's reach because alone it scores worse or the same.

- `chained_constant_store_split`: `A = (B = 0.0f);` on two volatile globals becomes two stores. The chain reads the
  inner store back (`lwc1` in the jump's delay slot); the game wrote both stores out.
- `arm_local_split`: a float local the two arms of different `if`s each set (m2c names both `x`) gets a block-scoped
  local in the first arm. One name across both arms is one pseudo, so both arms' results land in the registers the
  second gives it; split, each arm gets its own, and gcc stops merging the arms' identical trailing store
  (cross-jumping) when the registers differ. 665 -> 255 here.
- `identical_return_collapse`: `if (p) { return E; } else { return E; }` (a search's leftover: the test keeps a
  parameter live to the end, which costs a `move` of it and shifts every later register) is just `return E;`.
- `packed_return_fold`: `{ s32 A = ..; s32 B = ..; return ((A & M) << S) | (B & M); }` becomes
  `{ A = ..; B = ..; do { } while (0); A = (A & M) << S; return A | (B & M); }`. The barrier keeps the scheduler from
  hoisting the shift above the second operand's loads, and the reassigned `A` is a second set of the pseudo, which
  local allocation does not tie to the shift's result: the game's registers (`$a3` for the first half, `$v0/$v1` for
  the second). 765 -> 370 by the barrier, 370 -> 0 by the fold.

None changes what is computed; the exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

CHAIN = 'chained_constant_store_split'
ARM = 'arm_local_split'
FOLD = 'packed_return_fold'
COLLAPSE = 'identical_return_collapse'
FAMILIES = (CHAIN, ARM, FOLD, COLLAPSE)
LIMIT = 8

_IDENT = r'[A-Za-z_]\w*'
_TYPES = r'(?:f32|f64|float|double|s32|u32|s16|u16|s8|u8|int)'


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, opening, end) if end else None


def chain_variants(source, name):
    """[(CHAIN, source)]: `A = (B = c);` with a literal c written as two stores."""
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    pat = re.compile(rf'(?P<a>{_IDENT})\s*=\s*\(\s*(?P<b>{_IDENT})\s*=\s*(?P<c>-?[\d.]+f?)\s*\)\s*;')
    found = [m for m in pat.finditer(clean, opening, end)]
    if not found:
        return []
    text = source
    for m in reversed(found):
        text = text[:m.start()] + f"{m['b']} = {m['c']};\n    {m['a']} = {m['c']};" + text[m.end():]
    return [(CHAIN, text)]


def _blocks(clean, opening, end):
    """Brace blocks directly inside the function body, and one level down (an if/else arm): (start, end)."""
    out, depth, starts = [], 0, []
    for pos in range(opening, end):
        ch = clean[pos]
        if ch == '{':
            depth += 1
            starts.append(pos)
        elif ch == '}':
            start = starts.pop()
            if depth == 2:
                out.append((start, pos + 1))
            depth -= 1
    return sorted(out)


def _split_arm(source, name, var):
    """The source with `var` given a block local in the first arm that sets it first, or None."""
    part = _body(source, name)
    if not part:
        return None
    clean, opening, end = part
    blocks = _blocks(clean, opening, end)
    decl = re.compile(rf'^[ \t]*(?P<t>{_TYPES})\s+{var}\s*;', re.M)
    found = decl.search(clean, opening, end)
    if not found or clean.count('{', opening, found.start()) != clean.count('}', opening, found.start()) + 1:
        return None
    first_sets = []
    for start, stop in blocks:
        m = re.search(rf'(?<![\w.>]){var}\b', clean[start + 1:stop])
        if m and re.match(r'\s*=(?!=)', clean[start + 1 + m.end():stop]):
            first_sets.append((start, stop))
    if not first_sets:
        return None
    start, stop = first_sets[0]
    fresh = f'{var}_arm'
    if re.search(rf'\b{fresh}\b', clean):
        return None
    # outside the arms, the next mention must set the variable: nothing may read this arm's value
    outside = [m for m in re.finditer(rf'(?<![\w.>]){var}\b', clean[stop:end - 1])
               if not any(a <= stop + m.start() < b for a, b in first_sets)]
    if outside and not re.match(r'\s*=(?!=)', clean[stop + outside[0].end():end]):
        return None
    if not outside and len(first_sets) < 2:
        return None  # scoped to one arm already: nothing to split
    inner = source[start + 1:stop - 1]
    renamed = re.sub(rf'(?<![\w.>]){var}\b', fresh, inner)
    indent = re.match(r'\s*', renamed)[0].lstrip('\n') or '    '
    renamed = f'\n{indent}{found["t"]} {fresh};' + renamed
    return source[:start + 1] + renamed + source[stop - 1:]


def arm_variants(source, name):
    """[(ARM, source)]: a local set at the top of two sibling arms gets its own block local in one of them, each
    such local alone and then all of them in one child (both halves of an arm's pair were needed: 305 alone)."""
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    names = re.findall(rf'^[ \t]*{_TYPES}\s+({_IDENT})\s*;', clean[opening:end], re.M)
    out, everything = [], source
    for var in names:
        one = _split_arm(source, name, var)
        if one:
            out.append((ARM, one))
        more = _split_arm(everything, name, var)
        if more:
            everything = more
    if everything != source and len(out) > 1:
        out.append((ARM, everything))
    return out[:LIMIT]


def fold_variants(source, name):
    """[(FOLD, source)]: the packed return's first half reassigned after a barrier, alone and with it."""
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    pat = re.compile(
        rf'(?P<d1>[ \t]*)(?P<t>{_TYPES})\s+(?P<a>{_IDENT})\s*=\s*(?P<ea>[^;]+);\s*'
        rf'(?P<d2>[ \t]*)(?P=t)\s+(?P<b>{_IDENT})\s*=\s*(?P<eb>[^;]+);\s*'
        rf'return\s*\(\(\s*(?P=a)\s*&\s*(?P<m>0x[0-9A-Fa-f]+|\d+)\s*\)\s*<<\s*(?P<s>\d+)\s*\)\s*\|\s*'
        rf'\(\s*(?P=b)\s*&\s*(?P=m)\s*\)\s*;')
    m = pat.search(clean, opening, end)
    if not m:
        return []
    ind = m['d1'] or '    '
    head = f"{ind}{m['t']} {m['a']} = {m['ea']};\n{ind}{m['t']} {m['b']} = {m['eb']};\n"
    barrier = f"{ind}do {{ }} while (0);\n"
    fold = (f"{ind}{m['a']} = ({m['a']} & {m['m']}) << {m['s']};\n"
            f"{ind}return {m['a']} | ({m['b']} & {m['m']});")
    plain = f"{ind}return (({m['a']} & {m['m']}) << {m['s']}) | ({m['b']} & {m['m']});"
    out = []
    for tail in (barrier + fold, barrier + plain, fold):
        new = head + tail
        out.append((FOLD, source[:m.start()] + new + source[m.end():]))
    return out


def collapse_variants(source, name):
    """[(COLLAPSE, source)]: a test of a plain name whose two arms return the same expression, as that return."""
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    pat = re.compile(rf'if\s*\(\s*!?{_IDENT}\s*\)\s*\{{\s*return\s+(?P<e>[^;{{}}]+);\s*\}}\s*'
                     r'else\s*\{\s*return\s+(?P=e)\s*;\s*\}')
    m = pat.search(clean, opening, end)
    if not m:
        return []
    return [(COLLAPSE, source[:m.start()] + f"return {m['e']};" + source[m.end():])]


def variants(source, name):
    out = []
    for step in (chain_variants, arm_variants, collapse_variants, fold_variants):
        out.extend(step(source, name))
    # the collapsed return is what the fold needs, so offer them as one child as well
    for _, collapsed in collapse_variants(source, name):
        out.extend(fold_variants(collapsed, name))
    return out[:LIMIT * 4]
