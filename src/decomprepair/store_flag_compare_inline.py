"""m2c's float compare flags (`v = 1; if (!(x <= K)) { v = 0; }`) written back as the compares the game combined.

For a float comparison used as a value, GCC 2.7.2 on MIPS emits `li v,1` in a `bc1t`'s delay slot and `move v,$zero`
after it; m2c reads that back as a flag set to 1 and cleared under the negated compare, and a test that combines two
of them with `&`, or with `|` over `^ 1`:

    var_v1_7 = 1;
    if (!(x <= 0.0002f)) { var_v1_7 = 0; }
    var_v0_6 = 1;
    if (!(x >= (-0.0002f))) { var_v0_6 = 0; }
    t = 0.4f;
    if (((var_v1_7 ^ 1) | (var_v0_6 ^ 1)) != 0) { t = 0.1f; }

The game wrote the compares in the test: `if (!(x <= 0.0002f) | !(x >= (-0.0002f)))` (a "not near zero" macro). The
`xori` of each negated compare then follows its own flag (the target's `xori $a0, $v0, 1` sits in the next `bc1t`'s
delay slot), where m2c's separate flags put both `xori`s after the second compare and change the registers. Four such
tests in a 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller routine, all rewritten together:
2245 -> 1245 in the isolated judge (the `&` tests compile the same either way).

store_flag_compare_inline
    A flag local `V` set by `V = 1;` and `if (!(CMP)) { V = 0; }` (CMP a comparison of names, fields and literals: no
    call, no assignment), read once afterwards in an `if` condition as `(V ^ 1)` or plain `V`, with nothing between
    that writes CMP's names (and no store at all when CMP reads memory): `(V ^ 1)` becomes `!(CMP)`, `V` becomes
    `(CMP)`, the two statements go, and a condition left as `((A) | (B)) != 0` loses its `!= 0`. A flag reused for
    several such webs is handled web by web. Every web together first, then each test's webs alone.

Hypothesis from the match (not from the compiler source): each negated compare is expanded to its store-flag and
`xori` where it is written. The exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY = 'store_flag_compare_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'

_DEF = re.compile(
    rf'^(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*1\s*;[ \t]*\n'
    rf'(?P<mid>(?:[ \t]*[^;{{}}\n]*;[ \t]*\n){{0,3}}?)'
    rf'(?P<test>[ \t]*)if\s*\(\s*!\s*\((?P<cmp>[^;{{}}]*?(?:<=|>=|<|>|==|!=)[^;{{}}]*?)\)\s*\)\s*'
    rf'(?:{{\s*(?P=var)\s*=\s*0\s*;\s*}}|(?P=var)\s*=\s*0\s*;)[ \t]*\n', re.M)


def _span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    return (span[0] + head.end() - 1, span[1]) if head else None


def _mention(var):
    return re.compile(rf'(?<![\w.>]){re.escape(var)}\b')


def _written(name, text):
    return bool(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text)
                or re.search(rf'(?:\+\+|--)\s*{re.escape(name)}\b|\b{re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', text))


def _plain(cmp):
    """A comparison with no call, assignment, increment, conditional or comma."""
    return not re.search(rf'\b{IDENT}\s*\(|\+\+|--|[^=!<>]=(?!=)|\?|,', cmp)


def _memory(cmp):
    return bool(re.search(r'->|\*|\[|[A-Za-z_)\]]\s*\.', cmp))


def _stores(text, body):
    """True when `text` assigns anything but a local the function declares (a store a memory read can't pass)."""
    for m in re.finditer(r'(?P<lhs>[^;{}()]*?)\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text):
        lhs = m['lhs'].strip()
        if not lhs or lhs[-1] in '=!<>':
            continue
        if not re.fullmatch(IDENT, lhs) or not re.search(rf'^[ \t]*[A-Za-z_][\w ]*?[ \t*]+{re.escape(lhs)}[ \t]*;', body, re.M):
            return True
    return False


def _condition(text, at):
    """(start, end) of the parenthesised condition of the first `if` at or after `at`, or None."""
    m = re.compile(r'\bif\s*\(').search(text, at)
    if not m:
        return None
    depth = 0
    for j in range(m.end() - 1, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if depth == 0:
                return m.end() - 1, j + 1
    return None


def _webs(source, name):
    """Each flag web: (def start, def end, condition start, condition end, var, cmp)."""
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for hit in _DEF.finditer(clean, span[0], span[1]):
        var, cmp = hit['var'], hit['cmp'].strip()
        mid = hit['mid'] or ''
        if not _plain(cmp) or _mention(var).search(mid) or any(_written(n, mid) for n in re.findall(IDENT, cmp)):
            continue
        if re.search(r'\b(?:if|else|while|for|do|switch|case|default|goto|return|break|continue)\b', mid):
            continue
        mention = _mention(var)
        use = mention.search(clean, hit.end(), span[1])
        if not use:
            continue
        cond = _condition(clean, clean.rfind('\n', 0, use.start()))
        if not cond or not cond[0] < use.start() < cond[1] or cond[0] < hit.end():
            continue
        if len(mention.findall(clean, cond[0], cond[1])) != 1:
            continue
        between = clean[hit.end():cond[0]]
        if mention.search(between):
            continue
        names = {n for n in re.findall(IDENT, cmp)}
        if any(_written(n, between) for n in names):
            continue
        if _memory(cmp) and _stores(between, clean[span[0]:span[1]]):
            continue
        # after this read, the flag is dead until a new `V = 1;` (or never read again)
        after = mention.search(clean, cond[1], span[1])
        if after and not re.match(rf'{re.escape(var)}\s*=\s*1\s*;', clean[after.start():]):
            continue
        out.append((hit.start(), hit.end(), cond[0], cond[1], var, cmp, hit.start('mid'), hit.end('mid')))
    return out


def _rewrite(source, webs):
    edits = []
    conds = {}
    for start, end, c0, c1, var, cmp, m0, m1 in webs:
        edits.append((start, m0, ''))
        edits.append((m1, end, ''))
        conds.setdefault((c0, c1), []).append((var, cmp))
    for (c0, c1), uses in conds.items():
        text = source[c0:c1]
        for var, cmp in uses:
            text = re.sub(rf'\(\s*{re.escape(var)}\s*\^\s*1\s*\)', lambda _m, c=cmp: f'!({c})', text)
            text = _mention(var).sub(lambda _m, c=cmp: f'({c})', text)
        m = re.fullmatch(r'\(\s*\((?P<inner>.*)\)\s*!=\s*0\s*\)', text, re.S)
        if m and _balanced(m['inner']):
            text = f'({m["inner"].strip()})'
        edits.append((c0, c1, text))
    for a, b, text in sorted(edits, reverse=True):
        source = source[:a] + text + source[b:]
    return source


def _balanced(text):
    depth = 0
    for c in text:
        depth += c == '('
        depth -= c == ')'
        if depth < 0:
            return False
    return depth == 0


def _drop_unused(source, name, names):
    span = _span(source, name)
    if not span:
        return source
    for var in names:
        if len(_mention(var).findall(_blank(source), span[0], span[1])) == 1:
            source = re.sub(rf'^[ \t]*(?:[su](?:8|16|32)|int|char|short|unsigned int)[ \t]+{re.escape(var)}[ \t]*;[ \t]*\n',
                            '', source, count=1, flags=re.M)
    return source


def variants(source, name):
    webs = _webs(source, name)
    if not webs:
        return []
    groups = {}
    for web in webs:
        groups.setdefault((web[2], web[3]), []).append(web)
    out = []
    names = {w[4] for w in webs}
    out.append((FAMILY, _drop_unused(_rewrite(source, webs), name, names)))
    if len(groups) > 1:
        for group in groups.values():
            out.append((FAMILY, _drop_unused(_rewrite(source, group), name, {w[4] for w in group})))
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
