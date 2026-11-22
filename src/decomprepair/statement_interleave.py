"""Move one plain assignment across a few independent neighbours, so a beam can interleave two runs of statements.

GCC 2.7.2 (KMC, N64) schedules inside a basic block roughly in source order, so the order of independent
statements decides which loads share a latency slot and which register each value gets. In one 2,122-instruction
animation function the original wrote `x = a; t = b; y = c; mm = m; t2 = d; z = e;` where the draft had all of the
`x, y, z` statements, then all of the `t` statements: the best of the 35 ways to interleave two such runs was 24
instructions closer than the draft's, and no adjacent swap reaches it without passing through a worse order.

A proposal moves one statement up or down past at most `REACH` statements of the same run, and proposals are dealt
round-robin across the function's runs so a long function does not spend the cap on its first. Measured on that
function with the three tail sites in the draft order (114 differing instructions): a width-3 beam over only these
proposals and the compiler reached the best hand-found ordering (99) in five levels and about 600 compiles, so give
it a budget of hundreds, not tens. A run is consecutive
single-line assignments at one indentation with no calls, increments, branches or stores through a pointer; the moved
statement and the ones it crosses must not name each other's destination (so every proposal reads and writes the same
values), and the destinations must be different variables. Aliasing between a stack variable whose address was taken
and a pointer read can still reorder a load; the normal judge and a later review decide, as for other orderings.
"""
import re

from .csource import _blank, find

FAMILY = 'statement_interleave'
FAMILIES = (FAMILY,)
REACH = 4
LIMIT = 48

_ID = r'[A-Za-z_]\w*'
_LINE = re.compile(rf'(?m)^([ \t]+)({_ID}(?:\s*\.\s*{_ID})*)\s*=(?!=)\s*([^;\n{{}}]+);[ \t]*$')


def _runs(clean, opening, end):
    runs, run = [], []
    for m in _LINE.finditer(clean, opening, end):
        rhs = m[3]
        if re.search(r'\(\s*\)|\w\s*\(|\+\+|--', rhs) or re.search(r'\b(?:return|goto|break|continue|case)\b', m[0]):
            run = _close(runs, run)
            continue
        if run and (clean[run[-1].end():m.start()] != '\n' or m[1] != run[-1][1]):
            run = _close(runs, run)
        run.append(m)
    _close(runs, run)
    return runs


def _close(runs, run):
    if len(run) > 1:
        runs.append(run)
    return []


def _root(target):
    return re.match(_ID, target).group(0)


def _names(text):
    return set(re.findall(_ID, text))


def _independent(a, b):
    ra, rb = _root(a[2]), _root(b[2])
    return ra != rb and ra not in _names(b[3]) and rb not in _names(a[3]) \
        and ra not in _names(b[2][len(rb):]) and rb not in _names(a[2][len(ra):])


def _increment_reset(source, clean, opening, end):
    """Swap an increment and an independent scalar reset, including across blank lines."""
    body = clean[opening + 1:end]
    pattern = re.compile(rf'(?m)^(?P<indent>[ \t]+)(?P<counter>{_ID})\+\+;(?P<space>\s*)'
                         rf'(?P=indent)(?P<flag>{_ID})\s*=\s*0;[ \t]*$')
    result = []
    for m in pattern.finditer(body):
        counter, flag = m['counter'], m['flag']
        if counter == flag:
            continue
        prefix = body[:m.start()].rstrip()
        if prefix and prefix[-1] not in ';{}:':
            continue  # an unbraced branch could govern only the increment
        for var in (counter, flag):
            decl = list(re.finditer(rf'(?:^|[;{{}}])\s*(?:s32|u32|int|long|unsigned\s+int)\s+{var}\s*;', body))
            shadows = re.findall(rf'(?:^|[;{{}}])\s*(?:(?:const|volatile|unsigned|signed|struct)\s+)*{_ID}\s+{var}\s*(?:[;=\[])', body)
            if len(decl) != 1 or len(shadows) != 1 or decl[0].end() > m.start():
                break
            before = body[:decl[0].start()]
            if before.count('{') != before.count('}') or re.search(rf'&\s*{var}\b', body):
                break
        else:
            a, b = opening + 1 + m.start(), opening + 1 + m.end()
            # Do not move comments, which may describe one of the statements.
            original = source[a:b]
            match = pattern.fullmatch(original)
            if not match:
                continue
            replacement = (f"{m['indent']}{flag} = 0;{m['space']}"
                           f"{m['indent']}{counter}++;")
            result.append((FAMILY, source[:a] + replacement + source[b:]))
    return result


def variants(source, name, arch='mips', asm='', header=''):
    """Each proposal moves one assignment of a run up or down across independent neighbours; MIPS only."""
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    targeted = _increment_reset(source, clean, opening, span[1])
    if re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return targeted[:LIMIT]
    per_run = []
    for run in _runs(clean, opening, span[1]):
        result = []
        lines = [source[m.start():m.end()] for m in run]
        for i in range(len(run)):
            for step in (-1, 1):
                for distance in range(1, REACH + 1):
                    j = i + step * distance
                    if not 0 <= j < len(run):
                        break
                    crossed = run[min(i, j):max(i, j) + 1]
                    if any(m is not run[i] and not _independent(run[i], m) for m in crossed):
                        break
                    order = list(range(len(run)))
                    order.insert(j, order.pop(i))
                    text = '\n'.join(lines[k] for k in order)
                    result.append((FAMILY, source[:run[0].start()] + text + source[run[-1].end():]))
        per_run.append(result)
    # round-robin across the runs, so a function with many of them does not spend the cap on the first
    result = targeted
    for k in range(max((len(r) for r in per_run), default=0)):
        result += [r[k] for r in per_run if k < len(r)]
    seen, unique = set(), []
    for item in result:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]
