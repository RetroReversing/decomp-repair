"""one_goto_run_copy: a labelled run that ends in `return`, copied over ONE of the `goto`s into it.

m2c joins arms that finish alike: one copy of the shared tail behind a label, `goto`s from the other arms. The source
may have written the tail again in just one arm, and that is visible even though the compiler's cross-jumping (after
register allocation) merges the copies back into one:

    if (...) { if (ok) { goto done; } }                if (...) { if (ok) { goto done; } }
    else if (...) { if (ok) { goto done; } }    ->     else if (...) { if (ok) { start(o); f(o, 300, 499); return; } }
    goto fail;                                         goto fail;
  done: start(o); f(o, 300, 499); return;            done: start(o); f(o, 300, 499); return;

With one copy of `f(o, 300, 499)` the argument registers `$a1`/`$a2` are set once in the function, so the first
scheduler treats those loads as a value's birth (`birthing_insn_p` in `sched.c`) and puts them right before the call,
after the address arithmetic of a store the call follows. With a second copy they are set twice, keep their ordinary
priority and come first, as in the target. A 249-instruction N64 function (`sn-n64-281 -G0 -mips3 -O2`) went from 90
to 0 with this one edit; `goto_shared_tail` and `goto_end_tail_copy` copy a run over every `goto` and gave 2290.

The program is the same: the run ends in `return`, so a copy does what the jump did. A run holds no labels, `case`,
`goto`, `break`, `continue` or declaration, no name it uses is declared in an inner block, and the label has at least
two `goto`s (with one, the copy is `goto_shared_tail`'s child). Children: one per `goto`, the last one first.
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import IDENT, _gotos, _labels, _paths, parse, walk
from .pattern_repairs import close

FAMILY = 'one_goto_run_copy'
FAMILIES = (FAMILY,)
LIMIT = 8
MAX_RUN = 800  # characters of the copied run
DECLARATION = re.compile(r'\s*(?!return\b|goto\b|sizeof\b)' + IDENT + r'(?:\s+|\s*\*+\s*)\(?\s*\*?\s*' + IDENT
                         + r'\s*(?:[\[=;,]|\)\s*\()')
RETURN = re.compile(r'\s*return\b')


def body(source, name):
    """(the blanked source, the statements of `name`'s body), or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:span[1]])
    opening = clean.find('{', span[0] + head.start(), span[1]) if head else -1
    closing = close(clean, opening, '{', '}') if opening >= 0 else None
    if not closing:
        return None
    inside = clean[opening:closing]
    if re.search(r'(?m)^\s*#', inside) or re.search(r'[=(,{]\s*&&|\b(?:__LINE__|__COUNTER__|asm|__asm__)\b', inside):
        return None
    try:
        return clean, parse(clean, opening + 1, closing - 1)
    except ValueError:
        return None


def declares(clean, statement):
    return statement.kind == 'simple' and DECLARATION.match(clean[statement.start:statement.end]) is not None


def inner_declarations(clean, stmts):
    """The identifiers of every declaration inside a block of the body (not the body's own declarations)."""
    names = set()
    for statement, _ in walk(stmts):
        for key in ('then', 'other', 'body'):
            part = statement.parts.get(key)
            for inner in (part['stmts'] if part else ()):
                if declares(clean, inner):
                    names.update(re.findall(IDENT, clean[inner.start:inner.end]))
    return names


def _runs(clean, stmts):
    """(run, gotos) for each labelled run that ends in `return` and has at least two `goto`s."""
    hidden = inner_declarations(clean, stmts)
    for label, trail in _paths(stmts):
        if label.kind != 'label':
            continue
        inside, at, _ = trail[-1]
        rest = inside[at + 1:]
        end = next((k for k, s in enumerate(rest) if s.kind == 'simple' and RETURN.match(clean[s.start:s.end])), None)
        if end is None:
            continue
        run = rest[:end + 1]
        gotos = [s for s, _ in _gotos(stmts, label.parts['name'])]
        if len(gotos) < 2 or _labels(run) or run[-1].end - run[0].start > MAX_RUN:
            continue
        if any(s.kind in ('case', 'goto', 'jump') or declares(clean, s) for s, _ in walk(run)):
            continue
        if hidden.intersection(re.findall(IDENT, clean[run[0].start:run[-1].end])):
            continue
        yield run, gotos


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _copy(source, run, goto):
    line = source.rfind('\n', 0, run[0].start) + 1
    base = _indent(source, run[0].start)
    text = source[line if not source[line:run[0].start].strip() else run[0].start:run[-1].end]
    rows = [row[len(base):] if row.startswith(base) else row.lstrip() for row in text.split('\n')]
    indent = _indent(source, goto.start)
    line = source.rfind('\n', 0, goto.start) + 1
    braced = source[:goto.start].rstrip().endswith(('{', ';', '}'))
    if braced and not source[line:goto.start].strip():
        replacement = ('\n' + indent).join(rows)
    else:  # `if (c) goto L;`: the copy has to stay one statement
        replacement = '{ ' + ' '.join(row.strip() for row in rows if row.strip()) + ' }'
    return source[:goto.start] + replacement + source[goto.end:]


def variants(source, name):
    """[(family, source)]: each labelled `return` run written over one of its `goto`s, the last `goto` first."""
    parsed = body(source, name)
    if not parsed:
        return []
    clean, stmts = parsed
    children = [_copy(source, run, goto) for run, gotos in _runs(clean, stmts)
                for goto in sorted(gotos, key=lambda s: -s.start)]
    return [(FAMILY, text) for text in list(dict.fromkeys(children))[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
