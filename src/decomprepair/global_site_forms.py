"""Each use of a global written as the target uses it: which global, what is added to it, what it is compared with.

A mirrored sibling of a matched function (one of a set of four rotations of one screen) reads the same two byte globals
in the same places but swaps which one gets the `- 1` before the float conversion, adds `+ 1` where the donor subtracted,
and tests `D < 23` where the donor tested `D != 0`. A transplant that renames symbols gets the shape (250 to 565 of a
16,000-point function under the donor's profile) and no further: where a donor's symbol is another symbol at only
some of its uses, one global rename moves all of them. The target says what each use is: the instructions after
`lb $v0, %lo(G)($v0)` are `addiu $v0, $v0, 1`, `slti $v0, $v0, 0x17`, `beqz $v0` or a plain use.

global_site_forms
    The target's loads of integer globals give facts: (symbol, added constant) for arithmetic and (symbol, comparison)
    for tests. Each source use of such a global in a float product (`G * f`, `(G - 1) * f`) takes any arithmetic fact of
    the same load width, and each test (`G != 0`, `G < N`) any comparison fact, polarity kept. Children differ in one
    use first, then two, and so on; a global the source no longer declares is declared like the one it replaces.

The exact judge decides every child. MIPS target assembly (spimdisasm spelling)."""
import itertools
import re

from .csource import _blank, find

FAMILY = 'global_site_forms'
FAMILIES = (FAMILY,)
LIMIT = 96
SITES = 8
_LOAD = re.compile(r'^(lb|lbu|lh|lhu|lw)\s+(\$\w+)\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)\s*\(')
_INT = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_BRANCH = re.compile(r'^(beqz|bnez|beqzl|bnezl)\s+(\$\w+)\s*,')


def _lines(asm):
    out = []
    for line in (asm or '').splitlines():
        text = re.sub(r'/\*.*?\*/', '', line).strip()
        if text and not text.startswith(('.', 'glabel', 'endlabel', '#')) and not text.endswith(':') and text != 'nop':
            out.append(text)
    return out


def _facts(asm):
    """({width: arithmetic facts}, {width: test facts}) from what follows each load of a global."""
    sums, tests = {}, {}
    lines = _lines(asm)
    for index, line in enumerate(lines):
        load = _LOAD.match(line)
        if not load:
            continue
        op, register, symbol = load.groups()
        after = lines[index + 1:index + 3]
        if not after:
            continue
        first = after[0]
        reg = re.escape(register)
        added = re.match(rf'addiu\s+{reg}\s*,\s*{reg}\s*,\s*(-?{_INT})$', first)
        less = re.match(rf'sltiu?\s+(\$\w+)\s*,\s*{reg}\s*,\s*(-?{_INT})$', first)
        branch = _BRANCH.match(first)
        if added:
            sums.setdefault(op, {})[(symbol, int(added[1], 0))] = None
        elif less:
            follow = _BRANCH.match(after[1]) if len(after) > 1 else None
            if follow and follow[2] == less[1]:
                tests.setdefault(op, {})[(symbol, 'less', int(less[2], 0))] = None
        elif branch and branch[2] == register:
            tests.setdefault(op, {})[(symbol, 'zero', 0)] = None
        elif re.match(rf'mtc1\s+{reg}\s*,', first):
            sums.setdefault(op, {})[(symbol, 0)] = None
    return sums, tests


def _loads(asm):
    return {m[3]: m[1] for m in (_LOAD.match(line) for line in _lines(asm)) if m}


def _sites(clean, start, end, symbols):
    """[(begin, finish, symbol, kind, polarity)] for each use of a loaded global in a product or a test."""
    names = '|'.join(re.escape(s) for s in sorted(symbols, key=len, reverse=True))
    if not names:
        return []
    found = []
    taken = []
    patterns = (
        ('sum', rf'\(\s*(?P<g>{names})\s*[+-]\s*{_INT}\s*\)(?=\s*\*)'),
        ('sum', rf'(?<![\w.\]>])\b(?P<g>{names})\b(?=\s*\*\s*[\d.])'),
        ('test', rf'\b(?P<g>{names})\b\s*(?P<c>!=|==)\s*0\b(?![xX.])'),
        ('test', rf'\b(?P<g>{names})\b\s*(?P<c><|>=)\s*{_INT}\b'),
    )
    for kind, pattern in patterns:
        for hit in re.compile(pattern).finditer(clean, start, end):
            if any(hit.start() < b and a < hit.end() for a, b in taken):
                continue
            taken.append(hit.span())
            polarity = hit['c'] in ('!=', '<') if kind == 'test' else True
            found.append((hit.start(), hit.end(), hit['g'], kind, polarity))
    return sorted(found)


def _write(kind, fact, polarity):
    if kind == 'sum':
        symbol, added = fact
        if not added:
            return symbol
        return f'({symbol} {"+" if added > 0 else "-"} {abs(added)})'
    symbol, test, bound = fact
    if test == 'zero':
        return f'{symbol} {"!=" if polarity else "=="} 0'
    return f'{symbol} {"<" if polarity else ">="} {bound}'


def _declare(source, wanted, like):
    """`source` with `wanted` declared the way `like` is, when it isn't declared yet."""
    clean = _blank(source)
    if re.search(rf'\bextern\b[^;\n]*\b{re.escape(wanted)}\b', clean):
        return source
    line = re.search(rf'^[ \t]*extern[^;\n\[\]()]*\b{re.escape(like)}\s*;[ \t]*\n', clean, re.M)
    if not line:
        return source
    text = source[line.start():line.end()]
    return source[:line.end()] + re.sub(rf'\b{re.escape(like)}\b', wanted, text) + source[line.end():]


def variants(source, name, asm=''):
    sums, tests = _facts(asm)
    loads = _loads(asm)
    if not sums and not tests:
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    sites = _sites(clean, span[0], span[1], loads)
    if not sites or len(sites) > SITES:
        return []
    choices = []
    for begin, end, symbol, kind, polarity in sites:
        facts = (sums if kind == 'sum' else tests).get(loads[symbol], {})
        current = ' '.join(source[begin:end].split())
        options = []
        for fact in facts:
            text = _write(kind, fact, polarity)
            if text != current:
                options.append((text, fact[0]))
        choices.append(options)
    out = []
    for count in range(1, len(sites) + 1):
        for picked in itertools.combinations(range(len(sites)), count):
            for options in itertools.product(*(choices[i] for i in picked)):
                child = source
                for index, (text, _) in sorted(zip(picked, options), reverse=True):
                    begin, end = sites[index][0], sites[index][1]
                    child = child[:begin] + text + child[end:]
                for index, (_, wanted) in zip(picked, options):
                    child = _declare(child, wanted, sites[index][2])
                if child not in out and child != source:
                    out.append(child)
                if len(out) >= LIMIT:
                    return [(FAMILY, c) for c in out]
    return [(FAMILY, c) for c in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
