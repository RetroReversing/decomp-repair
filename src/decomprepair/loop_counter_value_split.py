"""A loop's counter that the code after the loop reuses for an unrelated value gets its own local, and that value's
statements are weighted so it outranks the counters that follow (a KMC gcc 2.7.2 voice-table initialiser, 20 -> 0).

m2c names one integer `i` for the first loop's counter and, after the loop, for a fresh value (`i = g; ... i &= 0xFF;
if (i != 0) { ... j < i * 4 ... }`). Two things in the allocator then went wrong together (hypotheses, read from the
`-dl -dg` tables of that one function, not proved in the compiler source):

- the counter's `i << 2` index in the first loop records a preference for the hard register that holds the index temp,
  and the shared pseudo carries it into the later value, whose `value << 2` loop bound then asks for the same register,
  so the next loop's counter (allocated earlier, since it has more references) skips it;
- once the counter is split, the fresh value has only a few references and is allocated after that next counter, so
  the two swap registers. `do { ... } while (0);` counts every reference inside it once more (flow.c weights by loop
  depth), two nested wrappers lift the value above the counter at no instruction cost.

Neither edit changes the score alone (the split alone 20 -> 50, the wrappers alone 245) and the pair leaves a
branch-likely in the first loop (200); the third step, `init_sink_into_guard` (the next loop's counter initialised
inside its guard), brought it to 0. `variants` offers each edit and the whole chain as one child, so the search sees
the combination. The judge decides.

Shape: a `for (V = 0; ...) { ... }` loop (V an integer local) followed at the function's top level by `V = E;` (E not
reading V), a run of plain statements of which the last that mentions V ends the run, then an `if (` guard.
"""
import re

from .allocation_weight_combination import _sink_edits
from .integer_repair_support import IDENT, INTEGER, edit, view
from .pattern_repairs import close

FAMILY = 'loop_counter_value_split'
FAMILIES = (FAMILY,)
DEPTH = 2


def _declaration(part, variable):
    """(start, end, type, names) of the `T a, b, V;` line declaring V, or None."""
    for hit in re.finditer(rf'\b(?P<type>{INTEGER})\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})*)\s*;', part.clean[part.opening:part.end]):
        names = [n.strip() for n in hit['names'].split(',')]
        if variable in names:
            return part.opening + hit.start(), part.opening + hit.end(), hit['type'], names
    return None


def _python_statements(clean, start, end):
    """(start, end) of each top-level statement in clean[start:end]: a `;` ends one, a block ends at its brace."""
    out, at, depth, i = [], start, 0, start
    while i < end:
        c = clean[i]
        if c in '({[':
            depth += 1
        elif c in ')}]':
            depth -= 1
            if depth == 0 and c == '}':
                after = re.match(r'\s*(?:else\b|while\b)', clean[i + 1:end])
                if not after:
                    out.append((at, i + 1))
                    at = i + 1
        elif c == ';' and depth == 0:
            out.append((at, i + 1))
            at = i + 1
        i += 1
    return [(s + len(clean[s:e]) - len(clean[s:e].lstrip()), e) for s, e in out]


_statements = _python_statements
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _statements(clean, start, end):
        found = _scan.statements_counter_split(clean, start, end)
        if found is not NotImplemented:
            return [(s + len(clean[s:e]) - len(clean[s:e].lstrip()), e) for s, e in found]
        return _python_statements(clean, start, end)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body):
        return []
    clean, found = part.clean, []
    for loop in re.finditer(rf'\bfor\s*\(\s*(?P<v>{IDENT})\s*=\s*0\s*;', clean[part.opening:part.end]):
        variable, header = loop['v'], part.opening + loop.start()
        opening = clean.find('(', header)
        stop = close(clean, opening)
        brace = re.match(r'\s*\{', clean[stop:part.end]) if stop else None
        if not brace:
            continue
        body_end = close(clean, stop + brace.end() - 1, '{', '}')
        decl = _declaration(part, variable)
        if not body_end or not decl or f'{variable}_loop' in clean:
            continue
        after = _statements(clean, body_end, part.end - 1)
        fresh = next((k for k, (s, e) in enumerate(after)
                      if re.fullmatch(rf'{re.escape(variable)}\s*=(?!=)[^;]*;', clean[s:e])
                      and not re.search(rf'\b{re.escape(variable)}\b', clean[s:e].split('=', 1)[1])), None)
        if fresh is None or any(re.search(rf'\b{re.escape(variable)}\b', clean[s:e]) for s, e in after[:fresh]
                                if not clean[s:e].startswith('{')):
            continue
        run = []
        for s, e in after[fresh:]:
            if re.match(r'(?:if|for|while|do|switch)\b|\{', clean[s:e]):
                break
            run.append((s, e))
        mentions = [k for k, (s, e) in enumerate(run) if re.search(rf'\b{re.escape(variable)}\b', clean[s:e])]
        if not mentions:
            continue
        run = run[:mentions[-1] + 1]
        split = f'{variable}_loop'
        loop_text = clean[header:body_end]
        rename = [(header + m.start(), header + m.end(), split)
                  for m in re.finditer(rf'(?<![\w.>]){re.escape(variable)}\b', loop_text)]
        d_start, d_end, kind, _ = decl
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, d_start) + 1:])[0]
        split_edits = rename + [(d_end, d_end, f'\n{indent}{kind} {split};')]
        wrap = [(run[0][0], run[0][0], 'do{' * DEPTH), (run[-1][1], run[-1][1], '}while(0);' * DEPTH)]
        sink = _sink_edits(part)
        chain = split_edits + wrap + (sink[0] if sink else [])
        for label, edits in (('split', split_edits), ('split+weight', split_edits + wrap), ('chain', chain)):
            if label == 'chain' and not sink:
                continue
            found.append((FAMILY, edit(source, edits)))
    seen, out = set(), []
    for family, text in found:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out
