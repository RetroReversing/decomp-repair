"""A pointer set afresh in sibling arms, and a count that must out-rank it: the split and the weight in one child.

KMC GCC 2.7.2 at `-O1`: a dispatch (`if (mode == 0) { p = &T[0]; if (p[0] != n) { f = 1; } else if (p[1] != n - 1) ..
} else if (mode == 1) { p = &T[0]; ..`) whose every register but a few is right, with a count in the pointer's register
and the pointer in the count's (or the flag's). The target gives each arm a pointer of its own, so one shared `p` can
never fit: it needs a local per arm *and* the first arm's compare chain weighted, so the pointer and the count come
out in order. Each step alone scores no better (or worse) than the shared pointer, so the greedy chain stops there;
here they are one child:

  a pointer's webs split (`local_web_split`), then one block that names it wrapped in `do { } while (0);`
    (global.c's priority is `floor_log2 (refs) * refs / live length`, and flow.c counts a reference once more per loop);
  or the same with the `if` after an `else` wrapped (`else do { if (..) { .. } } while (0);`), the unit
    `run_weight_scope` does not offer because it is not a statement of a block;
  and, when the dispatch is guarded by a global (`if (G < K) {`) that the first arm reads again, that global held in a
    local read by the guard and that arm (the later arms keep their own load, as the target does): the held value is
    then one pseudo from the guard to the arm.

The wrappers are scaffolding no developer wrote; polishing removes them once the function is recorded as matched. The
allocator reasons are read from the compiler's behaviour, not confirmed in its source (hypotheses); the judge decides.
"""
import re

from . import local_web_split, run_weight_scope
from .integer_repair_support import IDENT, edit, view

SPLIT = 'sibling_arm_pointer_scope'
HELD = 'sibling_arm_held_count'
FAMILIES = (SPLIT, HELD)
LIMIT = 96
BLOCKS = 8
TAILS = 6
_ADDRESS = re.compile(rf'(?<![\w.>*])(?P<name>{IDENT})\s*=\s*(?P<value>&\s*{IDENT}(?:\s*\[\s*0\s*\])?|{IDENT})\s*;')
_BARRED = re.compile(r'\b(?:break|continue|goto|case|default|asm|__asm__|volatile|setjmp|longjmp)\b|(?<![\w?])[A-Za-z_]\w*\s*:(?!:)')


def _pointers(source, name):
    """Locals declared as pointers that take the same symbol's address in two places or more."""
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    found = {}
    for m in _ADDRESS.finditer(body):
        found.setdefault(m['name'], []).append(re.sub(r'\s+', '', m['value']))
    return [n for n, values in found.items()
            if len(values) > len(set(values)) and re.search(rf'\*\s*{re.escape(n)}\b[^;{{}}()=]*[;,=]', body)]


def _tails(source, name):
    """[(start, end)] of every `if` that follows an `else`, wrappable in a one-shot scope."""
    part = view(source, name)
    if not part:
        return []
    found = []
    for m in re.finditer(r'\belse\s+(?=if\b)', part.clean[part.opening:part.end]):
        start = part.opening + m.end()
        end = run_weight_scope._statement_end(part.clean, start, part.end - 1)
        if end > 0 and not _BARRED.search(part.clean[start:end]):
            found.append((start, end))
    return found


def _wrap(source, start, end):
    return edit(source, [(start, end, 'do { ' + source[start:end].strip() + ' } while (0);')])


def _weighted(source, name, pointers):
    """One-wrapper children of `source`: the compound blocks that name a split pointer, then the `else if` tails."""
    named = re.compile(rf'\b(?:{"|".join(map(re.escape, pointers))})(?:_\d+|_b\d+)?\b')
    blocks = [(a, b) for a, b, text, _, kind in run_weight_scope.units(source, name) if kind == 0 and named.search(text)]
    tails = [(a, b) for a, b in _tails(source, name) if named.search(source[a:b])]
    # the smallest tail is the compare chain's last test, the likeliest to move one priority
    tails.sort(key=lambda span: (span[1] - span[0], span[0]))
    return [_wrap(source, a, b) for a, b in tails[:TAILS] + blocks[:BLOCKS]]


def _guard(source, name):
    """(global, guard condition span, first arm span, where to declare) of `if (G op K) { if (..) { first arm }`."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    head = re.compile(rf'(?<![\w.])if\s*\(\s*(?P<g>{IDENT})\s*(?:(?:!=|==|<=?|>=?)\s*-?\w+\s*)?\)\s*{{')
    for m in head.finditer(clean, part.opening + 1, part.end):
        g = m['g']
        declared = re.search(rf'\bextern\s+(?:(?:unsigned|signed)\s+)?{IDENT}\s+{re.escape(g)}\s*;', source)
        if not declared:
            continue
        before = clean[part.opening + 1:m.start()]
        if re.search(r'\b(?:if|for|while|do|switch|return|goto)\b|\b[A-Za-z_]\w*\s*\(', before):
            continue
        brace = m.end() - 1
        end = run_weight_scope._match(clean, brace, '{', '}')
        if end < 0:
            continue
        body = clean[brace:end]
        # the held copy is only the same program when nothing in the guarded code can write the global
        if re.search(rf'\b(?!if\b|while\b|for\b|switch\b|return\b|sizeof\b){IDENT}\s*\(', body):
            continue
        if re.search(rf'(?:\b{re.escape(g)}|\]|->\s*\w+)\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(g)}\b|'
                     rf'\b{re.escape(g)}\s*(?:\+\+|--)|(?<!&)&\s*{re.escape(g)}\b|(?:^|[;{{}}])\s*\*', body):
            continue
        inner = re.compile(r'(?<![\w.])if\s*\(').search(clean, brace + 1, end)
        if not inner:
            continue
        close = run_weight_scope._match(clean, inner.end() - 1, '(', ')')
        opening = re.compile(r'\s*{').match(clean, close) if close > 0 else None
        stop = run_weight_scope._match(clean, opening.end() - 1, '{', '}') if opening else -1
        if stop < 0 or not re.search(rf'\b{re.escape(g)}\b', clean[opening.end():stop]):
            continue
        return g, (m.start(), brace), (opening.end() - 1, stop), part.opening + 1
    return None


def _hold(source, name):
    found = _guard(source, name)
    if not found:
        return None
    g, condition, arm, top = found
    held = f'held_{g}'
    if re.search(rf'\b{re.escape(held)}\b', source):
        return None
    part = view(source, name)
    spots = [(a + m.start(), a + m.end()) for a, b in (condition, arm)
             for m in re.finditer(rf'(?<![\w.>]){re.escape(g)}\b', part.clean[a:b])]
    return edit(source, [(top, top, f'\n    int {held} = {g};')] + [(a, b, held) for a, b in spots])


def variants(source, name):
    pointers = _pointers(source, name)
    if not pointers:
        return []
    bases = [(source, False)]
    split = local_web_split.variants(source, name)
    bases += [(child, True) for _, child in split
              if any(not re.search(rf'\*\s*{re.escape(p)}\s*;', child) for p in pointers)]
    seen, per_base = {source}, []
    for base, was_split in reversed(bases):  # the split bases first: the shape the target usually wants
        for held in (_hold(base, name), None):
            start = held or base
            family = HELD if held else SPLIT
            children = ([held] if held and was_split else []) + _weighted(start, name, pointers)
            fresh = [(family, child) for child in children if child not in seen]
            seen.update(child for _, child in fresh)
            per_base.append(fresh)
    # take from each base in turn, so a cap never starves one shape
    result, at = [], 0
    while len(result) < LIMIT and any(at < len(group) for group in per_base):
        result += [group[at] for group in per_base if at < len(group)]
        at += 1
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 91, 'archs': ('mips',)}
