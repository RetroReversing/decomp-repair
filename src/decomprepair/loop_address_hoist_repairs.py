"""A repeated `&global` argument read once into a local pointer, with the scope of the local varied.

GCC 2.7 gives registers to the pseudos that live across calls in the order of floor_log2(refs) * refs / live length,
where each reference counts one more for every loop it sits in. A local pointer that stands for `&D_xxxx` in a loop
is a pseudo of its own: it takes a callee-saved register, and where it sits in that order against the loop counters
changes which counter gets which register. Which uses the local replaces matters as much as whether there is one:
the same address written out in a nested goto loop is a constant the compiler rebuilds there, so it competes for
nothing. (A near miss of 465 went to 405 with the local standing for the address in the outer loop only.)

For each global whose address is passed in three or more calls, this proposes the local with three scopes: every
use; the uses outside the nested loops; and, for each outermost loop, the uses in it with and without its nested
loops. The local is declared with the global's own type (`extern T g;` gives `T *`); a global whose type isn't
a plain declaration in the source is left alone. Only a bare `&g` argument is replaced, so the value is exactly
the one it stood for.
"""
import re

from .csource import _blank, find

LIMIT = 16
EARLIER = 2  # how many plain statements above a loop the assignment may also go (where it sits shifts the order of the setup)
USES = 3  # fewer repeats leave the compiler nothing to rank
SYMBOLS = 3  # the most repeated addresses of a function are tried, not every global it names
PREFIX = 'hoist_'


def _match(text, at, open_, close):
    """Index of the bracket closing the one at `at`, or -1."""
    depth = 0
    for index in range(at, len(text)):
        depth += (text[index] == open_)-(text[index] == close)
        if depth == 0:
            return index
    return -1


def _next(text, at):
    while at < len(text) and text[at].isspace():
        at += 1
    return at


def _loops(clean, start, end):
    """(start, end) of each loop in clean[start:end]: do, while and for statements, and goto loops (a label some
    later `goto` returns to, through the `if` block that holds the goto)."""
    found = []
    for m in re.finditer(r'\bdo\s*\{', clean[start:end]):
        close = _match(clean, start+m.end()-1, '{', '}')
        tail = re.compile(r'\s*while\s*\([^;]*\)\s*;').match(clean, close+1) if close > 0 else None
        if tail:
            found.append((start+m.start(), tail.end()))
    for m in re.finditer(r'\b(?:for|while)\s*\(', clean[start:end]):
        at = start+m.end()-1
        close = _match(clean, at, '(', ')')
        after = _next(clean, close+1) if close > 0 else len(clean)
        if after < end and clean[after] == '{':
            body = _match(clean, after, '{', '}')
            if body > 0:
                found.append((start+m.start(), body+1))
    for m in re.finditer(r'^[ \t]*([A-Za-z_]\w*)[ \t]*:(?!:)', clean[start:end], re.M):
        label = m[1]
        if label in ('default', 'public', 'private', 'protected'):
            continue
        gotos = [g for g in re.finditer(rf'\bgoto\s+{label}\s*;', clean[start+m.end():end])]
        if not gotos:
            continue
        stop = start+m.end()+gotos[-1].end()
        after = _next(clean, stop)
        if after < end and clean[after] == '}':
            opening = clean.rfind('{', start+m.end(), after)
            if opening > 0 and _match(clean, opening, '{', '}') == after:
                stop = after+1
        found.append((start+m.start(), stop))
    return sorted(set(found))


def _anchors(clean, at):
    """`at`, and the starts of up to EARLIER one-line statements right above it in the same block."""
    result = [at]
    line = clean.rfind('\n', 0, at)+1
    for _ in range(EARLIER):
        if line <= 0:
            break
        previous = clean.rfind('\n', 0, line-1)+1
        text = clean[previous:line-1]
        if not re.fullmatch(r'[ \t]*[^\s{}#:][^{}]*;[ \t]*', text) or re.match(r'[ \t]*(?:return|goto|break|continue)\b', text):
            break
        result.append(previous)
        line = previous
    return result


def _declared(clean, before, symbol):
    """The type `extern T symbol;` gives, or None when the source doesn't declare it that plainly."""
    for m in re.finditer(rf'^[ \t]*extern\s+([^;()=\[\]*]+?)\s+{symbol}\s*;', clean[:before], re.M):
        kind = ' '.join(m[1].split())
        if not re.search(r'\b(?:volatile|struct|union|enum)\b', kind):
            return kind
    return None


def _edit(text, start, end, edits):
    """`text` with the `(at, old_end, new)` replacements and the insertions `(at, at, new)` applied."""
    for at, stop, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:at]+new+text[stop:]
    return text


def variants(source, name):
    """Variants of function `name` where a repeated `&global` argument goes through a local pointer."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or PREFIX in clean[start:end]:
        return []
    body = clean[opening:end]
    loops = _loops(clean, opening, end)
    counts = {}
    for m in re.finditer(r'&[ \t]*([A-Za-z_]\w*)\b', body):
        at = opening+m.start()
        before = clean[:at].rstrip()[-1:]
        after = clean[_next(clean, opening+m.end())] if _next(clean, opening+m.end()) < end else ''
        if before in ('(', ',') and after in (',', ')'):
            counts.setdefault(m[1], []).append((at, opening+m.end()))
    result = []
    line_end = clean.find('\n', opening)
    for symbol in sorted(counts, key=lambda s: (-len(counts[s]), s))[:SYMBOLS]:
        uses = counts[symbol]
        kind = _declared(clean, start, symbol)
        local = re.search(rf'\b[A-Za-z_]\w*[ \t*]+\**{symbol}\s*[;=,\[]', clean[opening:end])
        if len(uses) < USES or kind is None or local or line_end < 0:
            continue
        for text in _scopes(source, clean, (start, end), loops, symbol, kind, uses, line_end):
            if text != source and ('loop_address_hoist', text) not in result:
                result.append(('loop_address_hoist', text))
    return result[:LIMIT]


def _scopes(source, clean, span, loops, symbol, kind, uses, line_end):
    """The variants for one global: the local replacing `uses` (the spans of its `&symbol`) in each scope."""
    start, end = span
    pointer = PREFIX+symbol
    declaration = (line_end+1, line_end+1, f'    {kind} *{pointer};\n')

    def inside(use, region):
        return region[0] <= use[0] and use[1] <= region[1]

    def nested(use):
        return sum(1 for r in loops if inside(use, r)) > 1

    def outer(region):
        return not any(r != region and r[0] <= region[0] and region[1] <= r[1] for r in loops)

    def build(chosen, anchor):
        """The variant that replaces `chosen`, with the assignment on the line `anchor` starts."""
        if len(chosen) < 2:
            return None
        line = clean.rfind('\n', 0, anchor)+1
        indent = re.match(r'[ \t]*', clean[line:]).group()
        edits = [declaration, (line, line, f'{indent}{pointer} = &{symbol};\n')]
        edits += [(a, b, pointer) for a, b in chosen]
        return _edit(source, start, end, edits)

    def first(chosen):
        """Where the assignment goes: before the outermost loop holding the first use, else before its line."""
        held = [r for r in loops if inside(chosen[0], r) and outer(r)]
        return held[0][0] if held else chosen[0][0]

    flat = [u for u in uses if not nested(u)]
    options = [build(uses, first(uses)), build(flat, first(flat or uses))]
    for region in (r for r in loops if outer(r)):
        held = [u for u in uses if inside(u, region)]
        for anchor in _anchors(clean, region[0]):
            options.append(build([u for u in held if not nested(u)], anchor))
            options.append(build(held, anchor))
    return [text for text in options if text]
