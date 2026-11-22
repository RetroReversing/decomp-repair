"""A global counter's increment computed before the guard that tests it: the increment back inside the guard.

Game code bumps a bounded global counter as `if (count < LIMIT) { count++; ... }`. m2c reads it back with the sum
taken before the test and stored inside the arm, `v = count + 1; if (count < LIMIT) { ...; count = v; ... }`, often
with the arguments of the call that follows copied into locals first (`a = sp23; b = sp25; count = v; f(a, ..., b)`)
and, in a saved best, wrapped in identity inline helpers (`static u32 inline_fn2(u32 x) { return (u32) x; }`).

On an 842-instruction N64 lit-actor drawer (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, scoring 2) the target loads
the counter once into the register the compare reads and fills the branch's delay slot with the increment
(`lbu $v1, count; sltiu $v0, $v1, 10; beqz $v0, ...; addiu $v1, $v1, 1`): written as `count++` inside the arm the
compiler did the same, while the m2c form kept the sum in a register of its own (`addiu $t0, $v0, 1` before the
compare, a `nop` in the slot). The arm's copies and the identity helpers had to go in the same step: with either left,
the cross-jumped tails of the two arms that call the same function differed and the score rose (4075 with them gone
against 5720 and 6040 with them kept). With a matrix-pool bump of the same shape (`v = used + 1; if (used < limit)
{ used = v; base = ... + (v << 6); }`) in the same function both sites went 3712 -> 3640, and with the display-list
cursor as records (`display_cursor_record`) 1370. That the delay-slot fill follows from the increment's place is a
hypothesis read from the output (reorg.c fills the slot from the fall-through), not confirmed in the compiler source.

`guarded_increment_sink` offers, for `V = G + 1;` (G a global, read through casts or `*(T *) &G`) right before
`if (COND) {` where the arm assigns `G = V;` and V is read nowhere but in that arm, the function with `G++;` first in
the arm, V replaced by G after it and the early sum gone; `guarded_increment_sink_inlined` also folds the arm's plain
copies (`a = b;` with `a` read once, in the arm) into their use and unwraps identity inline helpers there. Each is
offered for every site alone and for all sites at once. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_increment_sink'
INLINED_FAMILY = 'guarded_increment_sink_inlined'
FAMILIES = (FAMILY, INLINED_FAMILY)
LIMIT = 6
TYPES = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64', 'int', 'unsigned', 'signed', 'char', 'short', 'long',
         'void', 'f32', 'const', 'volatile'}
SUM = re.compile(rf'(?P<v>{IDENT})\s*=\s*(?P<read>[^;{{}}=+]+?)\s*\+\s*1\s*;\s*(?=if\s*\()')
HELPER = re.compile(rf'(?:static\s+)?inline\s+(?:static\s+)?[\w\s*]+?\b(?P<name>{IDENT})\s*\(\s*[\w\s*]+?\b(?P<arg>{IDENT})\s*\)\s*'
                    rf'\{{\s*return\s*(?:\(\s*[\w\s]+\)\s*)?(?P=arg)\s*;\s*\}}')
COPY = re.compile(rf'(?P<x>{IDENT})\s*=\s*(?P<y>{IDENT})\s*;')


def _global(read):
    """The one global a read like `G`, `((u8) G)` or `(*((s32 *) (&G)))` names, else None."""
    names = [n for n in re.findall(IDENT, read) if n not in TYPES]
    if len(names) != 1 or re.sub(IDENT, '', read).strip(' \t\n()*&'):
        return None
    return names[0]


def _words(text, word):
    return list(re.finditer(rf'(?<![\w.>]){re.escape(word)}\b', text))


def _top_statements(clean, start, end):
    """(start, end) of each statement directly in the block `clean[start:end]`; nested blocks count as one."""
    out, i, begin = [], start, start
    while i < end:
        ch = clean[i]
        if ch == '{':
            j = close(clean, i, '{', '}')
            if not j:
                return None
            i = j
            out.append((begin, i))
            begin = i
            continue
        if ch == ';':
            out.append((begin, i + 1))
            begin = i + 1
        i += 1
    return [(a + len(clean[a:b]) - len(clean[a:b].lstrip()), b) for a, b in out if clean[a:b].strip()]


def _sites(part, defined):
    clean, sites = part.clean, []
    body = clean[part.opening:part.end]
    for hit in SUM.finditer(clean, part.opening, part.end):
        g, v = _global(hit['read']), hit['v']
        if not g or g == v or g in defined:
            continue
        cond_open = clean.index('(', hit.end())
        cond_close = close(clean, cond_open, '(', ')')
        if not cond_close or not _words(clean[cond_open:cond_close], g):
            continue
        brace = re.match(r'\s*\{', clean[cond_close:])
        if not brace:
            continue
        b_open = cond_close + brace.end() - 1
        b_close = close(clean, b_open, '{', '}')
        if not b_close:
            continue
        statements = _top_statements(clean, b_open + 1, b_close - 1)
        if not statements:
            continue
        store = next((s for s in statements if re.fullmatch(rf'{re.escape(g)}\s*=\s*{re.escape(v)}\s*;', clean[s[0]:s[1]])), None)
        if not store:
            continue
        before = clean[b_open + 1:store[0]]
        after = clean[store[1]:b_close]
        if _words(before, g) or _words(before, v) or re.search(rf'(?<![\w.>]){re.escape(g)}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', after):
            continue
        sites.append(dict(g=g, v=v, sum=(hit.start(), hit.end()), open=b_open, close=b_close, store=store,
                          statements=statements))
    kept = []
    for site in sites:  # V may be reused by several sites (one per arm); read nowhere else
        v = site['v']
        spans = [(s['sum'][0], s['close']) for s in sites if s['v'] == v]
        loose = [u for u in _words(clean, v) if part.opening < u.start() < part.end
                 and not any(a <= u.start() < b for a, b in spans)]
        declared = re.findall(rf'(?m)^[ \t]*(?:{IDENT}[\s*]+)+{re.escape(v)}\s*;', body)
        if len(loose) == len(declared):
            kept.append(site)
    return kept


def _line(source, start, end):
    """A statement's span widened to its whole line when nothing else is on it."""
    head = source.rfind('\n', 0, start) + 1
    tail = source.find('\n', end)
    if not source[head:start].strip() and tail >= 0 and not source[end:tail].strip():
        return head, tail + 1
    return start, end


def _rewrite(source, clean, site, helpers, inline):
    g, v = site['g'], site['v']
    edits = [(*_line(source, site['sum'][0], site['sum'][0] + len(source[site['sum'][0]:site['sum'][1]].rstrip())), '')]
    store_start, store_end = site['store']
    arm = [s for s in site['statements'] if s[0] >= store_end]
    folded = {}
    if inline:
        for a, b in site['statements']:
            if a >= store_start:
                break
            copy = COPY.fullmatch(clean[a:b])
            if not copy or copy['x'] in (g, v):
                continue
            uses = [u for s in arm for u in _words(clean[s[0]:s[1]], copy['x'])]
            whole = _words(clean[site['open']:site['close']], copy['x'])
            if len(uses) == 1 and len(whole) == 2:
                folded[copy['x']] = copy['y']
                edits.append((*_line(source, a, b), ''))
    indent = re.search(r'[ \t]*$', source[:site['store'][0]])[0]
    edits.append((*_line(source, store_start, store_end), ''))
    edits.append((site['open'] + 1, site['open'] + 1, f'\n{indent}{g}++;'))
    names = {v: g, **folded}
    for a, b in arm:
        text = source[a:b]
        text = re.sub(rf'(?<![\w.>])({"|".join(map(re.escape, names))})\b', lambda m: names[m[1]], text)
        if inline and helpers:
            pattern = rf'(?<![\w.>])(?:{"|".join(map(re.escape, helpers))})\s*\(\s*({IDENT})\s*\)'
            text = re.sub(pattern, lambda m: m[1], text)
        if text != source[a:b]:
            edits.append((a, b, text))
    return edits


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    defined = set(re.findall(rf'(?m)^[ \t]*(?:{IDENT}[\s*]+)+({IDENT})\s*(?:\[[^\]]*\])?\s*[;=]', part.body))
    defined |= set(re.findall(rf'({IDENT})\s*[,)]', clean[clean.rfind('(', 0, part.opening):part.opening]))
    sites = _sites(part, defined)
    if not sites:
        return []
    helpers = [h['name'] for h in HELPER.finditer(clean[:part.opening])]
    result = []
    for inline, family in ((False, FAMILY), (True, INLINED_FAMILY)):
        groups = [[s] for s in sites] + ([sites] if len(sites) > 1 else [])
        for group in reversed(groups):  # all sites first: the steps of a late match pay off together
            edits = [e for s in group for e in _rewrite(source, clean, s, helpers, inline)]
            text = edit(source, edits)
            if text != source and all(text != seen for _, seen in result):
                result.append((family, text))
    inlined = [r for r in result if r[0] == INLINED_FAMILY]
    plain = [r for r in result if r[0] == FAMILY]
    return (inlined[:LIMIT // 2] + plain)[:LIMIT]
