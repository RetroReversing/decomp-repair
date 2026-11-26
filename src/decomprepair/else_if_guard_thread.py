"""Consecutive `else if` arms that open with the same test, nested under it so its false case jumps past all of them.

`if (p[0] == x && B) { X } else if (p[0] == x && C) { Y } else Z` makes GCC (KMC 2.7.2 at -O1, which does not thread
jumps) send the first failing `p[0] == x` to the second arm, which loads and tests it again. A target that sends it
straight to `Z` was written with the test once around the arms: `if (p[0] == x) { if (B) { X goto L; } if (p[0] == x
&& C) { Y goto L; } } Z L:;` (a measured 84-instruction predicate: 10 -> 0 with the other repairs of that chain, one branch
target). The second arm keeps its own copy of the test, as the target reads it again.

The terms count as the same test when they are textually equal after a local assigned once from a global that the
function never stores is replaced by that global. Arms whose later tests have a call, a `++`/`--` or an assignment are
left alone: the skipped evaluation must be free of effects. At most 4 proposals; the judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'else_if_guard_thread'
FAMILIES = (FAMILY,)
LIMIT = 4

_IF = re.compile(r'\bif[ \t\n]*\(')
_ELSE = re.compile(r'[ \t\n]*else\b[ \t\n]*')
_ALIAS = re.compile(r'(?<![\w.>])(?P<local>[A-Za-z_]\w*)[ \t]*=[ \t]*(?P<global>[A-Za-z_]\w*(?:\[\d+\])?)[ \t]*;')
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\b(?!sizeof\b)[A-Za-z_]\w*[ \t]*\(')


def _python_close(text, at, opening, closing):
    depth = 0
    for position in range(at, len(text)):
        depth += text[position] == opening
        depth -= text[position] == closing
        if depth == 0:
            return position
    return None


def _statement_end(text, at):
    """The offset after the statement at `at`: a block, an `if` with its `else`, or up to its `;`."""
    while at < len(text) and text[at] in ' \t\n':
        at += 1
    if at >= len(text):
        return None
    if text[at] == '{':
        end = _python_close(text, at, '{', '}')
        return None if end is None else end + 1
    hit = _IF.match(text, at)
    if hit:
        arm = _arm(text, at)
        if arm is None:
            return None
        other = _ELSE.match(text, arm[2])
        return _statement_end(text, other.end()) if other else arm[2]
    end = text.find(';', at)
    return None if end < 0 or '{' in text[at:end] else end + 1


def _arm(text, at):
    """(condition span, body span, end) of the `if` at `at`, whose body is a brace block."""
    hit = _IF.match(text, at)
    if not hit:
        return None
    paren = hit.end() - 1
    close = _python_close(text, paren, '(', ')')
    if close is None:
        return None
    body = close + 1
    while body < len(text) and text[body] in ' \t\n':
        body += 1
    if body >= len(text) or text[body] != '{':
        return None
    end = _python_close(text, body, '{', '}')
    return None if end is None else ((paren + 1, close), (body + 1, end), end + 1)


def _terms(condition):
    """The top-level `&&` terms; None when a top-level `||` makes the first term no necessary condition."""
    out, depth, start = [], 0, 0
    for position, char in enumerate(condition):
        depth += char in '(['
        depth -= char in ')]'
        if depth == 0 and condition.startswith('&&', position):
            out.append(condition[start:position].strip())
            start = position + 2
        elif depth == 0 and condition.startswith('||', position):
            return None
    out.append(condition[start:].strip())
    return out


def _aliases(body):
    """{local: global} for locals assigned once, from a global that the function never stores."""
    found = {}
    for hit in _ALIAS.finditer(body):
        local, value = hit['local'], hit['global']
        base = value.split('[')[0]
        stored = re.compile(rf'(?<![\w.>]){re.escape(base)}\b(?:\[[^\]\n]*\])?[ \t]*(?:[-+*/|&^]?=(?!=)|\+\+|--)')
        sets = re.compile(rf'(?<![\w.>]){re.escape(local)}\b[ \t]*(?:[-+*/|&^]?=(?!=)|\+\+|--)')
        if len(sets.findall(body)) == 1 and not stored.search(body) and re.search(rf'\b{re.escape(base)}\b', body):
            found[local] = value
    return found


def _canonical(term, aliases):
    for local, value in aliases.items():
        term = re.sub(rf'(?<![\w.>]){re.escape(local)}\b', value, term)
    term = re.sub(r'\s+', '', term)
    while term.startswith('(') and _python_close(term, 0, '(', ')') == len(term) - 1:
        term = term[1:-1]
    if term.count('==') == 1 and '&' not in term and '|' not in term:
        term = '=='.join(sorted(term.split('==')))
    return term


def variants(source, name):
    """Proposals: the arms that share their first test nested under it, with a `goto` past the rest of the chain."""
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    aliases = _aliases(clean[part.opening + 1:part.end])
    label = 'chain_done'
    if re.search(rf'\b{label}\b', clean):
        return []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        arms, at = [], hit.start()
        key = None
        while True:
            arm = _arm(clean, at)
            if arm is None:
                break
            (cs, ce), (bs, be), end = arm
            terms = _terms(clean[cs:ce])
            if not terms or len(terms) < 2:
                break
            first = _canonical(terms[0], aliases)
            if key is None:
                key = first
            elif first != key or any(_EFFECT.search(t) for t in terms):
                break
            if _EFFECT.search(terms[0]):
                break
            arms.append((cs, ce, bs, be, end))
            other = _ELSE.match(clean, end)
            if not other:
                break
            at = other.end()
        if len(arms) < 2:
            continue
        # the whole chain ends after the statement that follows the last shared arm's `else`
        final = arms[-1][4]
        other = _ELSE.match(clean, final)
        tail_start = other.end() if other else None
        chain_end = _statement_end(clean, tail_start) if tail_start is not None else final
        if chain_end is None:
            continue
        cs, ce = arms[0][0], arms[0][1]
        shared = _terms(source[cs:ce])
        if not shared:
            continue
        pieces = []
        for index, (cs, ce, bs, be, _) in enumerate(arms):
            terms = _terms(source[cs:ce])
            condition = ' && '.join(terms[1:] if index == 0 else terms)
            pieces.append(f"if ({condition}) {{{source[bs:be]} goto {label}; }}")
        tail = source[tail_start:chain_end] if tail_start is not None else ''
        text = f"{{ if ({shared[0]}) {{ {' '.join(pieces)} }} {tail} {label}:; }}"
        out.append((FAMILY, edit(source, [(hit.start(), chain_end, text)])))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
