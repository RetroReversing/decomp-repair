"""Loops that add a load base to every nonzero word of a table, written as one `static inline` helper.

Loaders that turn the offsets stored in a file into pointers walk several tables the same way. m2c writes one loop each,
over its own cursor, counter and temporaries:

    var_a0 = 0;
    if (var_a0 < count) {
        var_v1 = M2C_FIELD(arg0, void ***, 0xC);
        do {
            temp_v0 = *var_v1;
            var_a0 += 1;
            if (temp_v0 != NULL) { *var_v1 = (s32)temp_v0 + (s32)arg0; }
            var_v1 += 1;
        } while (var_a0 < count);
    }

The source called one helper per table, and the helper read its base into a local of its own:

    static inline void rebase(s32 *list, s32 n, s32 base) {
        s32 offset = base;
        s32 i;
        for (i = 0; i < n; i++) {
            if (list[i] != 0) { list[i] += offset; }
        }
    }

On GCC 2.7.2 (KMC, N64, -O2) each expansion then copies the base into a register of its own before its loop
(`move $a1,$a2` in every guard's delay slot), and the caller's base is one more copy (`move $a2,$s2`) when it is a
local set before the `if` that holds the calls. Neither copy survives with hand-written loops, or with a helper that
adds its parameter directly. On a 155-instruction sound-bank start (saved best 1423 under that profile) the helper
alone gives 188; without the helper's own `offset` local the clean spelling stays at 1665 (one function).

Children: the loops replaced with the base in a caller local set before the outermost statement that holds them
(`rebase_loop_helper`), with the local set beside the first call (`rebase_loop_helper_inner`), and with the base passed
straight to each call (`rebase_loop_helper_direct`). A loop is only replaced when its counter starts at 0, a bound
that is not a literal is guarded the way a `for` loop would be, and its cursor, counter and temporaries are not read
again, so the program is the same. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .scaffold_strip import unfence

BEFORE = 'rebase_loop_helper'
INNER = 'rebase_loop_helper_inner'
DIRECT = 'rebase_loop_helper_direct'
FAMILIES = (BEFORE, INNER, DIRECT)

HELPER = '__repair_rebase'
BASE = '__repair_base'

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_CAST = r'(?:\(\s*(?:s32|u32|int|void\s*\*|u8\s*\*|s8\s*\*|char\s*\*)\s*\)\s*)?'
_STEP = r'(?:{name}\s*\+=\s*1\s*;|{name}\+\+\s*;)'

_LOOP = re.compile(
    rf'\bdo\s*\{{\s*(?P<v>{_ID})\s*=\s*\*\s*(?P<p>{_ID})\s*;\s*'
    rf'(?:(?P<i1>{_ID})\s*\+=\s*1\s*;\s*)?'
    rf'if\s*\(\s*(?P=v)(?:\s*!=\s*(?:NULL|0))?\s*\)\s*\{{\s*\*\s*(?P=p)\s*=\s*{_CAST}\(?\s*{_CAST}(?P=v)\s*\+\s*'
    rf'{_CAST}(?P<base>{_ID})\s*\)?\s*;\s*\}}\s*'
    rf'(?:(?P<i2>{_ID})\s*\+=\s*1\s*;\s*)?'
    rf'(?P=p)\s*\+=\s*1\s*;\s*'
    rf'(?:(?P<i3>{_ID})\s*\+=\s*1\s*;\s*)?'
    rf'\}}\s*while\s*\(\s*(?P<cond>{_ID})\s*<\s*(?P<n>{_ID}|{_NUM})\s*\)\s*;')
_ASSIGN = re.compile(rf'(?<![\w.>])(?P<name>{_ID})\s*=(?!=)\s*(?P<value>[^;{{}}]*);[ \t]*')


def _flatten(body):
    """Bare `{ ... }` blocks (what unfencing leaves) opened into the statements around them."""
    for _ in range(64):
        clean = _blank(body)
        for hit in re.finditer(r'(?<=[;{}])\s*\{', clean):
            at = hit.end() - 1
            if not clean[:hit.start()].strip():
                continue
            end = close(clean, at, '{', '}')
            if not end or re.match(rf'\s*(?:{_ID}[\s*]+)+{_ID}\s*(?:;|=|\[)', clean[at + 1:end - 1]):
                continue
            body = body[:at] + body[at + 1:end - 1].strip() + body[end:]
            break
        else:
            return body
    return body


def _run_before(clean, at):
    """The run of plain `name = value;` statements that ends at `at`, as matches, earliest first."""
    run = []
    while True:
        start = max(clean.rfind(ch, 0, len(clean[:at].rstrip()) - 1) for ch in ';{}') + 1
        text = clean[start:at]
        hit = _ASSIGN.fullmatch(text.strip() or ' ')
        if not hit:
            return run
        lead = len(text) - len(text.lstrip())
        run.insert(0, _ASSIGN.match(clean, start + lead))
        at = start


def _guard(clean, first, last, counter, bound):
    """The `if (0 < bound) { first..last }` that holds nothing else, as (start, end), or None."""
    opening = len(clean[:first].rstrip()) - 1
    if opening < 0 or clean[opening] != '{':
        return None
    end = close(clean, opening, '{', '}')
    if not end:
        return None
    tail = clean[last:end - 1].strip()
    if tail and not re.fullmatch(rf'{counter}\s*=\s*0\s*;', tail):
        return None
    test = rf'(?:{counter}\s*<\s*{bound}|{bound}\s*>\s*0|0\s*<\s*{bound})'
    head = re.search(rf'\bif\s*\(\s*{test}\s*\)\s*$', clean[:opening])
    if not head or re.match(r'\s*else\b', clean[end:]):
        return None
    return head.start(), end


def _loop(body, clean, hit):
    """One loop as (start, end, list, count, base, names), or None when replacing it could change the program."""
    counters = {hit[g] for g in ('i1', 'i2', 'i3') if hit[g]}
    if counters != {hit['cond']} or sum(1 for g in ('i1', 'i2', 'i3') if hit[g]) != 1:
        return None
    counter, cursor, bound = hit['cond'], hit['p'], hit['n']
    run = _run_before(clean, hit.start())
    values = {m['name']: m for m in run}
    if cursor not in values:
        return None
    starts = [m for m in _ASSIGN.finditer(clean, 0, hit.start()) if m['name'] == counter]
    if not starts or starts[-1]['value'].strip() != '0':
        return None
    table = body[values[cursor].start('value'):values[cursor].end('value')].strip()
    used = [values[cursor]]
    count = bound
    if bound in values:
        count = values[bound]['value'].strip()
        used.append(values[bound])
    if counter in values:
        used.append(values[counter])
    if re.search(rf'\b(?:{cursor}|{counter})\b', count + ' ' + table):
        return None
    first = min(m.start() for m in used)
    # statements of the run that stay must not sit between the ones that go
    if any(m.start() > first and m not in used for m in run):
        return None
    guard = _guard(clean, first, hit.end(), counter, rf'(?:{re.escape(count)}|{bound})')
    if guard:
        start, end = guard
    elif re.fullmatch(_NUM, count) and int(count, 0) > 0:
        start, end = first, hit.end()
    else:
        return None
    names = {hit['v'], cursor, counter} | ({bound} if bound in values else set())
    return start, end, table, count, hit['base'], names


def _dead(body, names):
    """`names` after the loops are gone: their leftover `= 0;` stores and then unused declarations removed. None when
    a name is still read before it is set again."""
    for name in sorted(names):
        for _ in range(64):
            clean = _blank(body)
            decl = re.search(rf'^[ \t]*(?:{_ID}\s+)+\**\s*{name}\s*;[ \t]*\n', clean, re.M)
            uses = [m for m in re.finditer(rf'(?<![\w.>]){name}\b', clean)
                    if not (decl and decl.start() <= m.start() < decl.end())]
            if not uses:
                if decl:
                    body = body[:decl.start()] + body[decl.end():]
                break
            sets = [re.compile(rf'{name}\s*=(?!=)\s*[^;{{}}]*;[ \t]*\n?').match(clean, m.start()) for m in uses]
            if not sets[0]:
                return None
            zero = [bool(s) and bool(re.fullmatch(rf'{name}\s*=\s*0\s*;\s*', s[0]))
                    and not re.search(r'\)\s*$|\belse\s*$', clean[:s.start()]) for s in sets]
            if all(zero):  # never read again
                dead = sets
            else:  # a `= 0;` the next one repeats with no read or loop between
                dead = [one for i, one in enumerate(sets[:-1])
                        if zero[i] and zero[i + 1]
                        and not re.search(r'\b(?:for|while|do|goto)\b', clean[one.end():sets[i + 1].start()])][:1]
            if not dead:
                break
            for hit in reversed(dead):
                line = body.rfind('\n', 0, hit.start()) + 1
                lo = line if not body[line:hit.start()].strip() else hit.start()
                body = body[:lo] + body[hit.end():]
    return body


def _top_statement(clean, opening, at):
    """Where the statement of the function's own block that holds `at` starts."""
    depth, parens, start = 0, 0, opening + 1
    for i in range(opening + 1, at):
        ch = clean[i]
        parens += (ch == '(') - (ch == ')')
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        if depth == 0 and not parens and ch in ';}' and not re.match(r'\s*else\b', clean[i + 1:]):
            start = i + 1
    return re.compile(r'\s*').match(clean, start).end()


def _line(body, at, text):
    """`text` as its own line before `at`, with the indent of the statement there."""
    indent = body[body.rfind('\n', 0, at) + 1:at]
    indent = indent if not indent.strip() else '    '
    return body[:at] + text + '\n' + indent + body[at:]


def variants(source, name):
    """The base-adding loops as calls of one inline helper, the base reached three ways."""
    if HELPER in source or not re.search(r'\bdo\b', source):
        return []
    text = unfence(source, name) or source
    span = find(text, name)
    if not span:
        return []
    start, end = span
    function = re.sub(r'[ \t]*/\*(?:(?!\*/).)*?__repair\w*(?:(?!\*/).)*?\*/', '', text[start:end])
    body = _flatten(function)
    clean = _blank(body)
    found, taken = [], 0
    for hit in _LOOP.finditer(clean):
        loop = _loop(body, clean, hit)
        if loop and loop[0] >= taken:
            found.append(loop)
            taken = loop[1]
    if not found:
        return []
    base = found[0][4]
    found = [loop for loop in found if loop[4] == base]
    if re.search(rf'(?<![\w.>]){base}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{base}\b|&\s*{base}\b', clean):
        return []
    names = set().union(*(loop[5] for loop in found))
    if base in names:
        return []

    helper = (f'static inline void {HELPER}(s32 *list, s32 n, s32 base) {{\n'
              '    s32 offset = base;\n    s32 i;\n\n'
              '    for (i = 0; i < n; i++) {\n'
              '        if (list[i] != 0) {\n            list[i] += offset;\n        }\n    }\n}\n\n')

    out = []
    for family in FAMILIES:
        argument = f'(s32){base}' if family == DIRECT else BASE
        new = body
        for lo, hi, table, count, _, _ in reversed(found):
            new = new[:lo] + f'{HELPER}((s32 *)({table}), {count}, {argument});' + new[hi:]
        new = _dead(new, names)
        if new is None:
            return []
        if family != DIRECT:
            code = _blank(new)
            opening = code.index('{')
            at = code.index(HELPER + '((')
            if family == BEFORE:
                at = _top_statement(code, opening, at)
            new = _line(new, at, f'{BASE} = (s32){base};')
            new = new[:opening + 1] + f'\n    s32 {BASE};' + new[opening + 1:]
        child = text[:start] + helper + new + text[end:]
        if child not in [other for _, other in out]:
            out.append((family, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
