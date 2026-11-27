"""goto_end_tail_copy: a labelled run that ends a `void` function, copied over each `goto` into it with a `return;`.

m2c reads a flat `if`/`else if` chain whose arms end in the same calls as sibling guards that jump into the last one:

    if (mode == 1) { f(buf, a); y = 0xC8; goto draw; }
    if (mode == 2) { f(buf, b); y = 0xE6; goto draw; }
    if (mode == 3) { text = c; goto print; }
    if (mode == 4) {
        text = d;
    print:
        f(buf, text);
        y = 0xB4;
    draw:
        g(buf, y);
    }

The source made the calls in every arm, and cross-jumping after register allocation merged the identical tails. Written
with one shared run, the selectors are pseudos of their own and the arguments are loaded after the label instead of in
each arm. A 160-instruction N64 message function (`sn-n64-281 -G0 -mips3 -O2`) sat at 11440 in this form after 39
attempts and was 60 with the runs written out (0 with the callee's float parameter, `float_argument_prototype`).

`goto_shared_tail` (goto_structure_repairs) copies a run only when every `goto` already continues as the run's end does,
or the run ends in `return`/`break`; a jump out of one guard of a ladder continues with the next guard, so it declines.
In a `void` function a run that falls to the function's end can be copied anywhere with a `return;` behind it. The
program is the same: the copy does what the jump did, and leaves where the run left.

A run is what follows the label up to the end of its block, when only closing braces (and skipped `else` arms) lead from
there to the function's end: no enclosing loop or `switch`, no labels, `goto`, `break`, `continue`, loops or
declarations in the run. A run that holds a second label is reached after the inner one is copied out, so the labels are
taken in turn. Children: every such label copied out (the combination, which is what pays), then each label alone.
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import IDENT, LOOPS, _continuation, _gotos, _labels, _paths, parse, walk
from .pattern_repairs import close

FAMILY = 'goto_end_tail_copy'
FAMILIES = (FAMILY,)
LIMIT = 6
MAX_COPIED = 4000  # characters of copied text one rewrite may add
DECLARATION = re.compile(r'\s*(?!return\b|goto\b|sizeof\b)' + IDENT + r'(?:\s+|\s*\*+\s*)\(?\s*\*?\s*' + IDENT + r'\s*(?:[\[=;,]|\)\s*\()')


def _function(source, name):
    """(the body's statements) of a `void` function, or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:span[1]])
    if not head:
        return None
    at = span[0] + head.start()
    before = clean[max(clean.rfind(';', 0, at), clean.rfind('}', 0, at)) + 1:at]
    before = re.sub(r'(?m)^\s*#.*$', '', before)
    if not re.search(r'\bvoid\b', before) or '*' in before:
        return None
    opening = clean.find('{', at, span[1])
    closing = close(clean, opening, '{', '}') if opening >= 0 else None
    if not closing:
        return None
    body = clean[opening:closing]
    if re.search(r'(?m)^\s*#', body) or re.search(r'[=(,{]\s*&&|\b(?:__LINE__|__COUNTER__|asm|__asm__)\b', body):
        return None
    try:
        return clean, parse(clean, opening + 1, closing - 1)
    except ValueError:
        return None


def _shadowed(clean, stmts, text):
    """A name the run uses is declared in some inner block: a copy elsewhere could bind it differently."""
    names = set(re.findall(IDENT, text))
    for s, _ in walk(stmts):
        for key in ('then', 'other', 'body'):
            part = s.parts.get(key)
            for inner in (part['stmts'] if part else ()):
                if inner.kind == 'simple' and DECLARATION.match(clean[inner.start:inner.end]):
                    if names.intersection(re.findall(IDENT, clean[inner.start:inner.end])):
                        return True
    return False


def _runs(clean, stmts):
    """(label statement, its run, its gotos) for each run that may be copied."""
    for label, trail in _paths(stmts):
        if label.kind != 'label':
            continue
        if any(owner is not None and owner.kind in LOOPS for _, _, owner in trail):
            continue
        inside, at, _ = trail[-1]
        run = inside[at + 1:]
        gotos = _gotos(stmts, label.parts['name'])
        if not run or not gotos or _labels(run):
            continue
        if any(s.kind in ('case', 'goto', 'jump') or s.kind in LOOPS for s, _ in walk(run)):
            continue
        if any(s.kind == 'simple' and DECLARATION.match(clean[s.start:s.end]) for s in run):
            continue
        end = trail[:-1] + ((inside, len(inside) - 1, None),)
        if _continuation(clean, end):
            continue
        if _shadowed(clean, stmts, clean[run[0].start:run[-1].end]):
            continue
        yield label, run, [s for s, _ in gotos]


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _copy(source, label, run, gotos):
    first = source.rfind('\n', 0, run[0].start) + 1
    base = _indent(source, run[0].start)
    text = source[first if not source[first:run[0].start].strip() else run[0].start:run[-1].end]
    lines = [line[len(base):] if line.startswith(base) else line.lstrip() for line in text.split('\n')]
    if sum(len(line) for line in lines) * len(gotos) > MAX_COPIED:
        return None
    ends = re.match(r'\s*return\b', source[run[-1].start:run[-1].end])
    if not ends:
        lines.append('return;')
    edits = []
    for goto in gotos:
        indent = _indent(source, goto.start)
        line = source.rfind('\n', 0, goto.start) + 1
        if source[line:goto.start].strip():  # `if (c) goto L;`: the copy is one statement
            replacement = '{ ' + ' '.join(part.strip() for part in lines if part.strip()) + ' }'
        else:
            replacement = ('\n' + indent).join(lines)
            before = source[:goto.start].rstrip()
            if not before.endswith(('{', ';', '}')):
                replacement = '{ ' + ' '.join(part.strip() for part in lines if part.strip()) + ' }'
        edits.append((goto.start, goto.end, replacement))
    line = source.rfind('\n', 0, label.start) + 1
    start = line if not source[line:label.start].strip() else label.start
    end = label.end + (1 if source[label.end:label.end + 1] == '\n' else 0)
    edits.append((start, end, ''))
    for a, b, replacement in sorted(edits, reverse=True):
        source = source[:a] + replacement + source[b:]
    return source


def _children_of(source, name):
    parsed = _function(source, name)
    if not parsed:
        return []
    clean, stmts = parsed
    found = (_copy(source, *run) for run in _runs(clean, stmts))
    return [text for text in found if text is not None]


def variants(source, name):
    """[(family, source)]: all the runs that end the function copied out, then each one alone."""
    singles = _children_of(source, name)
    if not singles:
        return []
    whole = singles[0]
    for _ in range(8):  # an outer label's run is free once the inner label is gone
        more = _children_of(whole, name)
        if not more:
            break
        whole = more[0]
    unique = list(dict.fromkeys([whole, *singles]))
    return [(FAMILY, text) for text in unique[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
