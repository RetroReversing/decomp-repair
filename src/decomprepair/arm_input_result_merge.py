"""A block's own input local that only feeds an `if`/`else` whose arms both assign one result, written as that result:
`{ s16 t = E; if (t >= 0) { v = f(t); } else { v = -f(-t); } }` as `v = E; if (v >= 0) { v = f(v); } else { v = -f(-v); }`.

KMC GCC 2.7.2 (`-O2`, N64): the block-local `t` is its own pseudo, live into both arms (a global pseudo), whose only
copy preference is the call's argument register, so it is loaded straight into `$a0` (`lh $a0; bltz $a0; jal f; nop`).
Written as the result variable, the one pseudo is also set from the calls' `$v0`, so it is loaded into `$v0` and the
argument becomes a copy in the call's delay slot (`lh $v0; bltz $v0; jal f; move $a0, $v0`), the target's code. On a
1315-instruction sound-sequence interpreter's two pitch commands, 2510 -> 2070, where every spelling of the arms alone
(a ternary, `0 - t`, a `u16` read, a result local, an inline helper) compiled the same. The reading is from the output;
the judge decides.

Rewrites `T t = E;` (a block-scope declaration, or `t = E;` of a local) directly followed by an `if` whose then-arm and
else-arm are each the one statement `v = ...;` with the same `v`, when `t` is named nowhere after that `if` and `E`
names neither. The value is kept: `E` must be an integer of `t`'s own type (`*((T *) ...)` or `(T) ...`), or `t` must be
as wide as `v`. Up to `SUBSETS` sites give every combination; more give `LIMIT` single sites and one child with all of them.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'arm_input_result_merge'
FAMILIES = (FAMILY,)
LIMIT = 6
SUBSETS = 4
_INT = r'(?:unsigned\s+char|signed\s+char|unsigned\s+short|unsigned\s+int|unsigned\s+long|unsigned|short|char|int|long|u8|s8|u16|s16|u32|s32)'
_WIDE = {'u32', 's32', 'int', 'long', 'unsigned', 'unsigned int', 'unsigned long'}


def _skip_space(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _close(text, i, open_, close):
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_:
            depth += 1
        elif text[j] == close:
            depth -= 1
            if depth == 0:
                return j
    return -1


def _arm(clean, i):
    """The single `v = ...;` statement of a braced arm at `i`: (end after the brace, v, statement span) or None."""
    if i >= len(clean) or clean[i] != '{':
        return None
    end = _close(clean, i, '{', '}')
    if end < 0:
        return None
    inner = clean[i + 1:end]
    stmt = re.fullmatch(rf'\s*({IDENT})\s*=(?!=)([^;{{}}]*);\s*', inner)
    if not stmt:
        return None
    return end + 1, stmt.group(1)


def _block_end(clean, i, hi):
    """Where the block around `i` closes (a block-scope declaration's name may be declared again after it)."""
    depth = 0
    for j in range(i, hi):
        if clean[j] == '{':
            depth += 1
        elif clean[j] == '}':
            if depth == 0:
                return j
            depth -= 1
    return hi


def _declared_type(body, name):
    found = re.search(rf'(?m)^[ \t]*(?:register\s+)?({_INT})[ \t]+{re.escape(name)}[ \t]*[;=]', body)
    return re.sub(r'\s+', ' ', found.group(1)) if found else None


def _sites(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    sites = []
    head = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?:(?:register\s+)?(?P<type>{_INT})[ \t]+)?(?P<t>{IDENT})[ \t]*=(?!=)'
                      rf'[ \t]*(?P<e>[^;{{}}\n]+);[ \t]*\n')
    for found in head.finditer(clean, lo, hi):
        t = found['t']
        kind = re.sub(r'\s+', ' ', found['type']) if found['type'] else _declared_type(body, t)
        if not kind:
            continue
        i = _skip_space(clean, found.end())
        cond = re.match(r'if\s*\(', clean[i:])
        if not cond:
            continue
        paren = i + cond.end() - 1
        pend = _close(clean, paren, '(', ')')
        if pend < 0:
            continue
        then = _arm(clean, _skip_space(clean, pend + 1))
        if not then:
            continue
        j = _skip_space(clean, then[0])
        if not clean.startswith('else', j):
            continue
        other = _arm(clean, _skip_space(clean, j + 4))
        if not other or other[1] != then[1]:
            continue
        v, stop = then[1], other[0]
        if v == t:
            continue
        expr = found['e']
        if re.search(rf'\b(?:{re.escape(t)}|{re.escape(v)})\b', expr):
            continue
        vkind = _declared_type(body, v)
        if not vkind or vkind not in _WIDE:
            continue
        typed = re.match(rf'\s*(?:\*\s*\(\s*\(\s*{re.escape(kind)}\s*\*\s*\)|\(\s*{re.escape(kind)}\s*\))', expr)
        if not (typed or kind in _WIDE):
            continue  # `t` would truncate a value `v` keeps whole
        limit = _block_end(clean, stop, hi) if found['type'] else hi
        if re.search(rf'\b{re.escape(t)}\b', clean[stop:limit]):
            continue
        if not re.search(rf'\b{re.escape(t)}\b', clean[paren:stop]):
            continue
        sites.append((found, t, v, paren, stop))
    return sites


def _apply(source, sites):
    out = source
    for found, t, v, paren, stop in sorted(sites, key=lambda s: s[0].start(), reverse=True):
        arms = re.sub(rf'\b{re.escape(t)}\b', v, out[paren:stop])
        line = f"{found['ind']}{v} = {out[found.start('e'):found.end('e')].strip()};\n"
        gap = out[found.end():paren]
        out = out[:found.start()] + line + gap + arms + out[stop:]
    return out


def variants(source, name, header=''):
    sites = _sites(source, name)
    if 1 < len(sites) <= SUBSETS:
        # Sites that only pay off together (two arms of one interpreter, each its own command) and one that does not:
        # every combination, the singles first.
        picks = [[s for k, s in enumerate(sites) if mask >> k & 1] for mask in range(1, 1 << len(sites))]
        picks.sort(key=len)
    else:
        picks = [[site] for site in sites[:LIMIT]] + ([sites] if len(sites) > 1 else [])
    return [(FAMILY, _apply(source, pick)) for pick in picks]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
