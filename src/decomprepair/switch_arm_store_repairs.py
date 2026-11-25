"""Store in each switch arm: `v = X;` in every arm and one `G = v;` after the switch becomes `G = X;` in every arm.

m2c merges what the arms of a `switch` produce into one local and stores it once after the switch. The game's own
code often stored in each arm, and for GCC 2.x that is not the same code even when the instructions come out equal:
the identical stores at the end of the arms are merged late (cross-jumping, after the first scheduling pass), so the
store sits in a different scheduling block from the statements that follow the switch. With the store after the merge
it shares a block with the next call's argument setup, which the first scheduling pass then moves above the store; with
a store in each arm it cannot. On one GCC 2.7 N64 near miss the target had the store first and the argument setup
after it (8 differing words), and only this form reproduced it.

The shape, all of it required: a `switch (E) { ... }` whose arms each end in `break;` and each end with `v = X;` for
one and the same local `v`; then, after only the closing braces of plain blocks the switch ends (so no statement runs
between them), `G = v;` with `G` a global name; `v` mentioned nowhere else but its declaration; no arm expression
reading `G`, calling, assigning or stepping. The store moved into an arm runs right after the arm's value is computed,
exactly where the old one would have read it, so nothing observable moves. One variant; the compiler and the byte judge
decide. The reverse (arms that already store the same global, gathered into one local) is not offered: a store in an
arm that does more than that has no single place to collect."""
import re

from .csource import _blank, find
from .loop_address_hoist_repairs import _match, _next

FAMILY = 'switch_arm_store'
IDENT = r'[A-Za-z_]\w*'
_LABELS = re.compile(r'\s*(?:(?:case\s+[^:;{}]+|default)\s*:\s*)+')
_ASSIGN = re.compile(rf'\s*({IDENT})\s*=(?!=)\s*(.+?)\s*$', re.S)
_STORE = re.compile(rf'\s*({IDENT})\s*=(?!=)\s*({IDENT})\s*;')
_EFFECT = re.compile(rf'\b(?!sizeof\b|case\b){IDENT}\s*\(|\+\+|--|(?<![=!<>])=(?!=)')


def _top_breaks(clean, start, end):
    """Spans of the `break;` statements that sit directly in clean[start:end], not inside a nested block."""
    spans, depth, at = [], 0, start
    while at < end:
        char = clean[at]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 0:
            hit = re.compile(r'break\s*;').match(clean, at)
            if hit and not (at > start and (clean[at-1].isalnum() or clean[at-1] == '_')):
                spans.append((at, hit.end()))
                at = hit.end()
                continue
        at += 1
    return spans


def _last_statement(text):
    """(start offset, text) of the last `;`-ended statement of `text`, which must hold no nested block."""
    if '{' in text or '}' in text:
        return None
    pieces = [p for p in re.finditer(r'[^;]+;', text)]
    return (pieces[-1].start(), pieces[-1][0]) if pieces else None


def _python_encloses_plainly(clean, close, floor):
    """The `{` that the `}` at `close` ends, when it opens a bare block (not a loop, `if` or function body)."""
    depth, at = 0, close
    while at >= floor:
        if clean[at] == '}':
            depth += 1
        elif clean[at] == '{':
            depth -= 1
            if depth == 0:
                before = clean[:at].rstrip()
                return at if before and before[-1] in ';{}' else None
        at -= 1
    return None


_encloses_plainly = _python_encloses_plainly
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _encloses_plainly(clean, close, floor):
        found = _scan.open_if_floor(clean, close, floor, '{', '}', None)
        if found is not NotImplemented:
            if found is None:
                return None
            before = clean[:found].rstrip()
            return found if before and before[-1] in ';{}' else None
        return _python_encloses_plainly(clean, close, floor)


def _switches(clean, opening, end):
    for m in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        paren = opening+m.end()-1
        close = _match(clean, paren, '(', ')')
        if close < 0:
            continue
        brace = _next(clean, close+1)
        if brace < end and clean[brace] == '{':
            stop = _match(clean, brace, '{', '}')
            if stop > 0:
                yield brace, stop


def _arms(clean, brace, stop):
    """[(variable, expression, (assignment start, assignment end))] for the arms, or None unless every arm is one
    labelled run of statements ending in `v = X;` and `break;`."""
    inner_start = brace+1
    breaks = _top_breaks(clean, inner_start, stop)
    if len(breaks) < 2 or clean[breaks[-1][1]:stop].strip():
        return None
    arms, floor = [], inner_start
    for first, last in breaks:
        text = clean[floor:first]
        labels = _LABELS.match(text)
        if not labels:
            return None
        body = text[labels.end():]
        found = _last_statement(body)
        if not found or body[found[0]+len(found[1]):].strip():
            return None
        assign = _ASSIGN.match(found[1].rstrip(';'))
        if not assign:
            return None
        base = floor+labels.end()+found[0]+len(found[1])-len(found[1].lstrip())  # (the statement itself, not its indent)
        arms.append((assign[1], assign[2], (base, floor+labels.end()+found[0]+len(found[1]))))
        floor = last
    return arms


def variants(source, name):
    """[(label, source)] with each arm storing `G = X;` itself, or []."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or re.search(r'\b(?:asm|__asm__)\b', clean[start:end]):
        return []
    for brace, stop in _switches(clean, opening, end):
        arms = _arms(clean, brace, stop)
        if not arms or len({a[0] for a in arms}) != 1:
            continue
        var = arms[0][0]
        at = stop+1
        while True:  # only the ends of plain blocks may follow the switch before the store
            at = _next(clean, at)
            if at < end and clean[at] == '}' and _encloses_plainly(clean, at, opening):
                at += 1
                continue
            break
        store = _STORE.match(clean, at)
        if not store or store[2] != var or store[1] == var:
            continue
        target = store[1]
        mentions = re.findall(rf'(?<![\w.>]){re.escape(var)}\b', clean[opening:end])
        if len(mentions) != len(arms)+2:  # its declaration, each arm's assignment, the store
            continue
        if any(re.search(rf'(?<![\w.>]){re.escape(target)}\b|{_EFFECT.pattern}', arm[1]) for arm in arms):
            continue
        if re.search(rf'(?m)^[ \t]*(?!return\b|goto\b|else\b)[A-Za-z_][\w \t*]*[ \t*]{re.escape(target)}[ \t]*(?:\[[^\]]*\])?[ \t]*(?:=[^;]*)?;',
                     clean[opening:end]):
            continue  # `G` is declared in the function: a name that only looks global
        edits = [(a[2][0], a[2][1], f'{target} = {a[1]};') for a in arms]
        line = clean.rfind('\n', 0, store.start())+1
        tail = clean.find('\n', store.end())
        tail = len(clean) if tail < 0 else tail+1
        alone = clean[line:store.start()].strip() == '' and clean[store.end():tail].strip() == ''
        edits.append((line, tail, '') if alone else (store.start(), store.end(), ''))  # (the whole line goes)
        text = source
        for first, last, new in sorted(edits, reverse=True):
            text = text[:first]+new+text[last:]
        return [(FAMILY, text)]
    return []
