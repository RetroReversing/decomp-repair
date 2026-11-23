"""m2c's guard on a register that is known to be zero, written as the `u16` counter test it came from.

A `for (i = 0; i < n; i++)` over a `u16` counter that GCC 2.7.2 builds inside the else of a flag test comes back from
m2c as

    temp_v1 = p->flags & 4;
    if (temp_v1 != 0) { ... } else {
        var_s0 = 0;
        if (temp_v1 < p->count) {
            do { ...; var_s0 += 1; } while ((u32) (var_s0 & 0xFFFF) < p->count);
        }
    }

The loop's copied entry test compared the counter (`0`) with the bound, and cse (2.7.2) put the oldest register known
to hold 0 in its place: the flag the branch just found to be zero (`sltu $v0, $v1, $v0`). Written with the flag, as m2c
has it, cse knows the flag is 0 and folds the test to `count != 0` (`beqz`), and the flag's register is freed for the
`lhu`, so the arm loses its `sltu` and a register. Written with the counter (`u16 i; i = 0; if (i < n) do ... while (i <
n)`), the test comes back. In a 1134-instruction ray caster all six triangle loops had it (four object loops and two
actor loops; 5796 -> 5425 with the counters alone, and the counters then shared one register as in the target).

The rewrite applies only where the guard's register is provably zero on that path: the guard sits in the else of `if
(Z != 0)` / `if (Z)`, or inside an `if` whose condition requires `Z == 0` (`((s32) Z) == 0 && ...`, `!Z`). The counter's
declaration becomes `u16` and its `& 0xFFFF` masks go; its last store before the loop must be `= 0`. One child per loop
and one with every loop. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'zero_guard_u16_counter'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
WHILE = re.compile(r'\}\s*while\s*\(')
COND = re.compile(r'^\(?\s*\(u32\)\s*\(\s*(?P<count>' + IDENT + r')\s*&\s*0x[fF]{4}\s*\)\s*\)?\s*<\s*(?P<bound>.+)$', re.S)
GUARD = re.compile(r'^\s*(?P<zero>' + IDENT + r')\s*<\s*(?P<bound>.+?)\s*$', re.S)


def _norm(text):
    return re.sub(r'\s+', '', text)


def _strip(text):
    """`(x)` -> `x` while the outer parentheses enclose all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _ifs(clean, lo, hi):
    """(if start, condition start, condition end, then start, then end, else start, else end) of the `if`s in [lo, hi).
    The then and else parts are `{ }` blocks, or (an else) a following `if`'s whole statement."""
    found = []
    for hit in re.finditer(r'\bif\s*\(', clean[lo:hi]):
        start = lo + hit.start()
        paren = lo + hit.end() - 1
        cond_end = close(clean, paren)
        if not cond_end:
            continue
        brace = re.match(r'\s*\{', clean[cond_end:])
        if not brace:
            continue
        then_open = cond_end + brace.end() - 1
        then_end = close(clean, then_open, '{', '}')
        if not then_end:
            continue
        else_start = else_end = None
        tail = re.match(r'\s*else\b\s*', clean[then_end:])
        if tail:
            else_start = then_end + tail.end()
            if clean.startswith('{', else_start):
                else_end = close(clean, else_start, '{', '}')
            else:
                nested = re.match(r'if\s*\(', clean[else_start:])
                if nested:
                    end = close(clean, else_start + nested.end() - 1)
                    body = re.match(r'\s*\{', clean[end:]) if end else None
                    else_end = close(clean, end + body.end() - 1, '{', '}') if body else None
        found.append((start, paren + 1, cond_end - 1, then_open, then_end, else_start, else_end))
    return found


def _zero(clean, ifs, var, at):
    """Whether `var` is known to be 0 at `at`: in the else of a test of it, or under a condition requiring it."""
    v = re.escape(var)
    nonzero = re.compile(r'^\s*(?:\(\s*)*' + v + r'(?:\s*\))*\s*(?:!=\s*0[uUlL]*)?\s*$')
    iszero = re.compile(r'(?:\(\s*(?:\(\s*s32\s*\)\s*)?' + v + r'\s*\)|(?<![\w.>])' + v + r')\s*==\s*0\b|!\s*\(?\s*'
                        + v + r'\b')
    for start, c0, c1, t0, t1, e0, e1 in ifs:
        cond = clean[c0:c1]
        if e0 is not None and e1 and e0 <= at < e1 and nonzero.match(_strip(cond)):
            return True
        if t0 < at < t1 and iszero.search(cond) and '||' not in cond:
            return True
    return False


def _sites(source, name):
    span = find(source, name)
    if not span:
        return None, []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None, []
    ifs = _ifs(clean, opening, end)
    sites = []
    for hit in WHILE.finditer(clean, opening, end):
        paren = hit.end() - 1
        cond_end = close(clean, paren)
        if not cond_end or not re.match(r'\s*;', clean[cond_end:]):
            continue
        cond = COND.match(_strip(clean[paren + 1:cond_end - 1]))
        if not cond:
            continue
        count, bound = cond['count'], _norm(_strip(cond['bound']))
        body_end = hit.start()
        body_open = next((pos for pos in range(body_end, opening, -1)
                          if clean[pos] == '{' and close(clean, pos, '{', '}') == body_end + 1), None)
        if body_open is None or not re.search(r'\bdo\s*$', clean[opening:body_open]):
            continue
        do = clean.rfind('do', opening, body_open)
        guards = [g for g in ifs if g[3] < do < g[4]]
        if not guards:
            continue
        guard = max(guards, key=lambda g: g[3])
        test = GUARD.match(_strip(clean[guard[1]:guard[2]]))
        if not test or _norm(_strip(test['bound'])) != bound or test['zero'] == count:
            continue
        if not _zero(clean, ifs, test['zero'], guard[0]):
            continue
        stores = list(re.finditer(r'(?<![\w.>])' + re.escape(count) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)\s*([^;]*);',
                                  clean[opening:do]))
        if not stores or stores[-1][1].strip() not in ('0', '0U', '0u'):
            continue
        last = stores[-1]
        sites.append({'count': count, 'guard': guard, 'store': (opening + last.start(), opening + last.end()),
                      'cond': (guard[1], guard[2]), 'loop': (do, cond_end)})
    return clean, sites


def _apply(source, clean, sites, name):
    edits = []
    counts = set()
    for site in sites:
        count = site['count']
        counts.add(count)
        guard_start = site['guard'][0]
        c0, c1 = site['cond']
        test = GUARD.match(_strip(source[c0:c1]))
        edits.append((c0, c1, count + ' < ' + test['bound'].strip()))
        s0, s1 = site['store']
        if s0 > guard_start:  # the counter's `= 0` is inside the guard: it goes before it
            line0 = source.rfind('\n', 0, s0) + 1
            line1 = source.find('\n', s1)
            line1 = len(source) if line1 < 0 else line1 + 1
            if source[line0:s0].strip() == '' and source[s1:line1].strip() == '':
                edits.append((line0, line1, ''))
            else:
                edits.append((s0, s1, ''))
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, guard_start) + 1:]).group()
            g_line = source.rfind('\n', 0, guard_start) + 1
            if source[g_line:guard_start].strip() != '':
                return None
            if re.search(r'\belse\s*$', clean[:g_line]):
                # `else if (...)`: the store and the guard become the else's block
                stmt_end = site['guard'][6] or site['guard'][4]
                edits.append((g_line, g_line, indent + '{\n' + indent + count + ' = 0;\n'))
                edits.append((stmt_end, stmt_end, '\n' + indent + '}'))
            else:
                edits.append((g_line, g_line, indent + count + ' = 0;\n'))
    out = source
    for a, b, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        out = out[:a] + text + out[b:]
    span = find(out, name)
    if not span:
        return None
    body = out[span[0]:span[1]]
    for count in counts:
        c = re.escape(count)
        body = re.sub(r'\(\s*\(u32\)\s*\(\s*' + c + r'\s*&\s*0x[fF]{4}\s*\)\s*\)', count, body)
        body = re.sub(r'\(u32\)\s*\(\s*' + c + r'\s*&\s*0x[fF]{4}\s*\)', count, body)
        body = re.sub(r'\(\s*' + c + r'\s*&\s*0x[fF]{4}\s*\)', count, body)
        body = re.sub(r'(?<![\w.>])' + c + r'\s*&\s*0x[fF]{4}\b', count, body)
        decl = re.compile(r'(?m)^([ \t]*)(?:register\s+)?(?:(?:unsigned|signed)\s+)?(?:char|short|int|long|[su](?:8|16|32))'
                          r'(?:\s+int)?[ \t]+' + c + r'[ \t]*;')
        if not decl.search(body):
            return None
        body = decl.sub(lambda m: m.group(1) + 'u16 ' + count + ';', body, count=1)
    return out[:span[0]] + body + out[span[1]:]


def variants(source, name):
    clean, sites = _sites(source, name)
    if not sites:
        return []
    result = []
    seen = {source}
    for group in [[site] for site in sites] + ([sites] if len(sites) > 1 else []):
        child = _apply(source, clean, group, name)
        if child and child not in seen:
            seen.add(child)
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
