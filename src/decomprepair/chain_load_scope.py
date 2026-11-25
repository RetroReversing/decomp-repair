"""A pointer-chain load pinned behind the branch operand's load, in a scheduling scope (GCC 2.7.2, KMC, N64).

GCC 2.7.2 schedules each basic block before register allocation. A saved-register load that the branch below it does
not need (`var = **(p + 0x10);`, read here for a use after the branch) competes with the loads that feed the branch,
and the scheduler puts it in the hole the branch operand's load leaves, ahead of that load. One function sat at 210
with a single row wrong: the target read the branch operand's global pointer first and the chain's last load after
it. Four edits were needed together (COMPILER_MATCHING_LEARNINGS.md); none helps alone:

- the double dereference split into a pointer local and a final load (`tmp = *(p + 0x10); var = *tmp;`),
- the branch's first operand load (`*(u8 *)(g + 0x2D)`) read into a local ahead of the final load,
- the final load wrapped in `do { var = *tmp; } while (0);`, whose loop notes are scheduling boundaries, so it
  stays behind the operand's load instead of floating above it (the wrapper alone, or the local alone: 235),
- and m2c's identical `if (c) { X } else { X }` arms (a condition on an unset local, from a join m2c could not
  name) written once. That alone is worse (220), which is why a search that takes one step never keeps it.

Two families, so each can be tested: `identical_arm_collapse` writes two identical arms once; `chain_load_scope`
proposes the combination for a statement `v = *(*((T **) BASE));` followed (past plain `id = expr;` statements) by an
`if` whose condition starts with a plain integer load. Only MIPS (the GCC scheduler) is proposed.
"""
import re

from .csource import _blank, find

FAMILY = 'chain_load_scope'
COLLAPSE = 'identical_arm_collapse'
FAMILIES = (FAMILY, COLLAPSE)
LIMIT = 12

_ID = r'[A-Za-z_]\w*'
_INTEGER = r'(?:unsigned\s+|signed\s+)?(?:char|short|int|long)|[us](?:8|16|32)|(?:Field_)?[us](?:8|16|32)'
_CALL = re.compile(r'\w\s*\(|\+\+|--')
_PLAIN = re.compile(rf'\s*{_ID}\s*=(?!=)[^;{{}}]*;')


def _python_close(clean, start, left='(', right=')'):
    """Index just past the bracket matching the one at `start`, or None."""
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    pass
else:
    def _close(clean, start, left='(', right=')'):
        found = _scan.close_every(clean, start, left, right, True, None)
        return _python_close(clean, start, left, right) if found is NotImplemented else found


def _body(clean):
    return clean.find('{'), clean.rfind('}')


def _pad(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return line if not line.strip() else re.match(r'\s*', line)[0]


def _norm(text):
    return re.sub(r'\s+', '', text)


def _splice(source, edits):
    for a, b, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:a] + text + source[b:]
    return source


def _arms(clean, source):
    """(start, end, inner text) of each `if (c) { X } else { X }` whose two arms read the same and c has no effect."""
    found = []
    for hit in re.finditer(r'(?<![\w.])if\s*\(', clean):
        paren = hit.end() - 1
        after = _close(clean, paren)
        first = re.compile(r'\s*\{').match(clean, after) if after else None
        end = _close(clean, first.end() - 1, '{', '}') if first else None
        other = re.compile(r'\s*else\s*\{').match(clean, end) if end else None
        stop = _close(clean, other.end() - 1, '{', '}') if other else None
        if not stop or _CALL.search(clean[paren:after]) or re.search(r'(?<![=!<>])=(?!=)', clean[paren:after]):
            continue
        one = source[first.end():end - 1]
        if _norm(clean[first.end():end - 1]) == _norm(clean[other.end():stop - 1]) and _norm(one):
            found.append((hit.start(), stop, one))
    return found


def _dedent(inner, indent):
    lines = [line for line in inner.strip('\n').split('\n') if line.strip()]
    common = min(len(line) - len(line.lstrip()) for line in lines)
    return '\n'.join(line[common:] if n == 0 else indent + line[common:] for n, line in enumerate(lines))


def collapse(source, name):
    """Sources with identical-arm `if`s written once: every site together, then each site alone."""
    span = find(source, name)
    if not span:
        return []
    lo, hi = span
    clean = _blank(source)
    edits = [(lo + start, lo + end, _dedent(inner, _pad(source, lo + start)))
             for start, end, inner in _arms(clean[lo:hi], source[lo:hi])]
    if not edits:
        return []
    return [_splice(source, edits)] + ([_splice(source, [edit]) for edit in edits] if len(edits) > 1 else [])


def _chains(clean, lo, hi):
    """Each `v = *(*((T **) BASE));` statement: (start, end, v, start and end of `*((T **) BASE)`, T)."""
    for hit in re.finditer(rf'(?m)^[ \t]*({_ID})\s*=\s*\*\s*\(', clean[lo:hi]):
        outer = lo + hit.end() - 1
        after = _close(clean, outer)
        semicolon = re.compile(r'\s*;').match(clean, after) if after else None
        if not semicolon:
            continue
        inner = clean[outer + 1:after - 1]
        lead = len(inner) - len(inner.lstrip())
        cast = re.match(r'\*\s*\(\s*\(\s*((?:unsigned\s+|signed\s+|const\s+)*[\w ]+?)\s*\*\s*\*\s*\)', inner[lead:])
        if not cast or _close(inner, lead + inner[lead:].index('(')) != len(inner.rstrip()):
            continue
        yield lo + hit.start(), semicolon.end(), hit[1], (outer + 1 + lead, outer + 1 + len(inner.rstrip())), cast[1].strip()


def _operand(condition):
    """(start, end, type) of the condition's leftmost operand when it is a plain integer load `(*((T *) ...))`."""
    lead = len(re.match(r'[\s(]*', condition)[0])
    at = condition.rfind('(', 0, lead) if lead else -1
    if at < 0 or condition[:at].strip('( \t\n'):
        return None
    end = _close(condition, at)
    text = condition[at:end] if end else ''
    if not end or _CALL.search(text) or 'volatile' in text:
        return None
    cast = re.match(rf'\(\*\s*\(\s*\(\s*({_INTEGER})\s*\*\s*\)', text)
    return (at, end, cast[1]) if cast else None


def _uses(text, name):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\b', text)


def _scope(source, name):
    """Proposals of the combination on `source`."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    lo, hi = span
    opening = clean.find('{', lo, hi)
    out = []
    taken = set(re.findall(_ID, clean[lo:hi]))
    for start, end, var, (a, b), kind in _chains(clean, opening + 1, hi):
        between_end = end
        while True:
            plain = _PLAIN.match(clean, between_end)
            if not plain or _CALL.search(plain[0]) or _uses(plain[0], var):
                break
            between_end = plain.end()
        guard = re.compile(r'\s*if\s*\(').match(clean, between_end)
        stop = _close(clean, guard.end() - 1) if guard else None
        if not stop:
            continue
        paren = guard.end() - 1
        operand = _operand(clean[paren + 1:stop - 1])
        if not operand:
            continue
        x, y, width = operand
        load = source[paren + 1 + x:paren + 1 + y]
        if _uses(load, var):
            continue
        names = []
        for stem in ('chain_ptr', 'guard_load'):
            while stem in taken:
                stem += '_'
            taken.add(stem)
            names.append(stem)
        pointer, loaded = names
        pad = re.match(r'[ \t]*', source[start:])[0]
        block = (f'{pad}{pointer} = {source[a:b]};\n{pad}{loaded} = {load};\n'
                 f'{pad}do {{ {var} = *{pointer}; }} while (0);{source[end:between_end]}')
        new = _splice(source, [(start, between_end, block),
                               (paren + 1 + x, paren + 1 + y, loaded),
                               (opening + 1, opening + 1, f'\n  {kind} *{pointer};\n  {width} {loaded};')])
        out.append((FAMILY, new))
    return out


def variants(source, name, arch='mips', asm='', header=''):
    """Proposals: identical arms written once, and the chain-load scope with and without that collapse."""
    if arch != 'mips':
        return []
    out = []
    for once in collapse(source, name):
        out.append((COLLAPSE, once))
        out += _scope(once, name)
    out += _scope(source, name)
    seen, unique = set(), []
    for item in out:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]
