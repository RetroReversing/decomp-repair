"""A wide constant added in a statement, held in the local an earlier test's load went through, with the stores pinned.

On MIPS a constant that does not fit an `addiu` (`x + 0x8000`) is built in a register by its own `ori`/`lui`, and GCC 2.8.1's
first scheduler (sched.c `birthing_insn_p`) launches an insn whose destination pseudo is set exactly once as soon as it
is ready: written as a literal, the constant is a fresh pseudo set once, so its `ori` lands right above its `addu`. A
72-instruction N64 object update (SN64 GCC 2.8.1 `-G0 -mips3 -O2`) had the target's
`ori $v1, $zero, 0x8000` near the top of the block, in `$v1`, the register the previous block's test had loaded
(`lw $v1, 0x7C($v0); li $v0, 4; bne $v1, $v0`). One local for both values, `k = D->f; if (k != 4) return 0; ... k =
0x8000; obj->x = p->y + k;`, gives the constant pseudo two sets, so it is not boosted. Alone that was worse (190 ->
1050 by the isolated judge's scale): without the `ori` to fill the load's latency, the scheduler lifted the load of
`p->y` above the two stores through `p` (same base, other offsets: `memrefs_conflict_p` proves them disjoint). With the
load and those stores marked `volatile` (sched.c orders two references only when both are volatile) the block took the
target's order: 190 -> 70 in the app, each half alone no better.

constant_compare_temp_reuse
    For a statement ending `+ K;` (K a literal at least 0x8000: not an `addiu` immediate) and the nearest earlier
    `if (EXPR op C)` whose EXPR reads memory and calls nothing, a fresh `s32` local takes EXPR before the test and K
    before the statement. Then the same child with the load through `*(T *) (base + off)` in that statement and the
    stores through the same base in the statements just before it marked `volatile`. A candidate rewrite; the judge
    decides, and the `volatile` is scaffolding that reproduces the original's order, not a known original spelling."""
import re

from .csource import _blank, find

FAMILY = 'constant_compare_temp_reuse'
FAMILIES = (FAMILY,)
LIMIT = 4
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_WIDE = re.compile(rf'\+\s*({_NUM})[uU]?\s*;')
_TEST = re.compile(rf'\bif\s*\(\s*([^()]*(?:\([^()]*\)[^()]*)*?)\s*(==|!=|<=|>=|<|>)\s*(-?{_NUM})\s*\)')
_ACCESS = r'\*\s*\(\s*(?P<type>[A-Za-z_][\w ]*?)\s*(?P<stars>\*+)\s*\)\s*\(\s*(?P<base>[A-Za-z_]\w*)\s*\+\s*' \
          rf'(?P<off>{_NUM})\s*\)'


def _fresh(source):
    for name in ('k', 'kv', 'k2', 'k3', 'wide'):
        if not re.search(rf'\b{name}\b', source):
            return name
    return None


def _statement_start(clean, at):
    return max(clean.rfind(';', 0, at), clean.rfind('{', 0, at), clean.rfind('}', 0, at)) + 1


def _volatile(match):
    """`*(T *) (b + o)` written as a volatile access of the same type."""
    stars = match['stars']
    kind = match['type'].strip()
    if len(stars) > 1:
        inner = f'{kind} {stars[:-1]} volatile *'
    else:
        inner = f'volatile {kind} *'
    return f'*({inner}) ({match["base"]} + {match["off"]})'


def _pins(source, clean, stmt_start, stmt_end, opening):
    """Edits marking the load in the statement and the stores through its base just before it `volatile`."""
    loads = [m for m in re.finditer(_ACCESS, clean[stmt_start:stmt_end]) if 'volatile' not in m['type']]
    equal = clean.find('=', stmt_start, stmt_end)
    loads = [m for m in loads if stmt_start + m.start() > equal >= 0]
    if len(loads) != 1:
        return None
    load = loads[0]
    edits = [(stmt_start + load.start(), stmt_start + load.end(), _volatile(load))]
    at = stmt_start
    while True:
        previous = _statement_start(clean, at - 1) if at > opening + 1 else at
        text = clean[previous:at]
        if previous >= at or clean[previous - 1] != ';':
            break
        store = re.match(rf'\s*{_ACCESS}\s*=(?!=)[^;]*;\s*$', text)
        if not store or store['base'] != load['base'] or 'volatile' in store['type']:
            break
        edits.append((previous + text.index('*', store.start()), previous + text.index(')', store.end('off')) + 1,
                      _volatile(store)))
        at = previous
    return edits if len(edits) > 1 else None


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not head:
        return []
    opening = span[0] + head.end() - 1
    local = _fresh(source[span[0]:span[1]])
    if local is None:
        return []
    out = []
    for wide in _WIDE.finditer(clean, opening, span[1]):
        if int(wide[1], 0) < 0x8000:
            continue
        stmt = _statement_start(clean, wide.start())
        tests = [t for t in _TEST.finditer(clean, opening, stmt)
                 if ('*' in t[1] or '->' in t[1]) and not re.search(r'\w\s*\(', t[1].replace('sizeof', ''))
                 and not re.search(r'(?<![=!<>])=(?!=)|\+\+|--', t[1])]
        if not tests:
            continue
        test = tests[-1]
        test_stmt = _statement_start(clean, test.start())
        indent_test = re.match(r'\s*', source[test_stmt:])[0].split('\n')[-1]
        indent_stmt = re.match(r'\s*', source[stmt:])[0].split('\n')[-1]
        line_test = test_stmt + len(re.match(r'\s*', source[test_stmt:])[0])
        line_stmt = stmt + len(re.match(r'\s*', source[stmt:])[0])
        edits = [
            (test.start(1), test.start(1) + len(test[1].rstrip()), local),
            (line_test, line_test, f'{local} = {source[test.start(1):test.end(1)].strip()};\n{indent_test}'),
            (wide.start(1), wide.end(1) + (1 if source[wide.end(1):wide.end(1) + 1] in 'uU' else 0), local),
            (line_stmt, line_stmt, f'{local} = {wide[1]};\n{indent_stmt}'),
            (opening + 1, opening + 1, f'\n    s32 {local};'),
        ]
        out.append((FAMILY, _apply(source, edits)))
        pins = _pins(source, clean, stmt, wide.end(), opening)
        if pins:
            out.append((FAMILY, _apply(source, edits + pins)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
