"""Loop-depth weights hidden in macros: unwrap the one-shot `do { } while (0)` everywhere at once, then re-wrap a few uses.

GCC 2.x counts every reference to a pseudo register once per loop depth (flow.c: `REG_N_REFS += loop_depth`), and
global.c ranks the saved registers by `floor_log2(uses) * uses / live_length`. A `do { ... } while (0)` is still a loop
when the registers are counted, so each statement inside it counts double. A macro that expands to one (the usual
"statement macro") puts that doubling on every use of it. A parameter that every arm of a function stores through
(`*dist = -*dist` in eight returns) then has far more uses than the original's, and takes a saved register before the
address temporaries that should rank above it: the diff is a swap of $s3 and $s4 on dozens of rows, and no
single rewrite moves it because one wrapper is only +2 of the ~16 uses that decide it.

The existing one_shot_scope/one_shot_unwrap rewrites unwrap one wrapper of the function body at a time and never look
inside a macro, and loop_weight_scope only adds wrappers. This family changes the whole set at once:

- macro_one_shot_unwrap: a `#define NAME(...) do { ... } while (0)` becomes `{ ... }` (each macro alone, and every one
  together), and every `do { ... } while (0);` of the function body together;
- macro_one_shot_rewrap: with the macros already unwrapped, one or two uses of a brace macro are wrapped again
  (`do { NAME(...); } while (0);`). The right number of re-wrapped uses is what puts the pseudo between its neighbours,
  and which uses hardly matters, so pairs are offered as well as single uses.

An unwrapped macro changes the program only where it was used as part of a larger statement, so a macro is left alone
unless every use is a whole statement `NAME(...);` that is not the unbraced body of an `if`/`else`/loop."""
import itertools
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('macro_one_shot_unwrap', 'macro_one_shot_rewrap')
LIMIT = 40
SITES = 12
CONTROL = re.compile(r'\b(?:break|continue|goto|case|default)\b')
LINE = re.compile(r'^[ \t]*#[ \t]*define[ \t]+(?P<name>' + IDENT + r')(?P<params>\([^)\n]*\))?(?P<space>[ \t]*)(?P<text>(?:[^\n\\]|\\\n|\\(?!\n))*)$', re.M)
WRAPPED = re.compile(r'(?P<open>do[ \t\\\n]*\{)(?P<body>.*)(?P<close>\}[ \t\\\n]*while[ \t\\\n]*\([ \t\\\n]*0[ \t\\\n]*\))[ \t]*$', re.S)


def macros(source):
    """Every macro whose text is a statement block: dicts with its name, kind ('wrapped' do-while or 'braced'), the span
    of its whole definition, the span of the wrapper text to rewrite, and its body."""
    found = []
    for line in LINE.finditer(source):
        text = line['text']
        base = line.start('text')
        wrapped = WRAPPED.fullmatch(text)
        if wrapped:
            found.append({'name': line['name'], 'kind': 'wrapped', 'define': (line.start(), line.end()), 'body': wrapped['body'],
                          'open': (base + wrapped.start('open'), base + wrapped.end('open')),
                          'close': (base + wrapped.start('close'), base + wrapped.end('close'))})
            continue
        stripped = text.strip()
        if stripped.startswith('{') and stripped.endswith('}') and close(stripped, 0, '{', '}') == len(stripped):
            found.append({'name': line['name'], 'kind': 'braced', 'define': (line.start(), line.end()), 'body': stripped[1:-1]})
    return found


def uses(clean, name, definition):
    """The statement uses `NAME(...);` of a function-like macro after its definition, or None when any use is part of
    something larger (an operand, an unbraced if/else/loop body, an object-like use)."""
    found = []
    for hit in re.finditer(r'\b' + re.escape(name) + r'\b', clean):
        if definition[0] <= hit.start() < definition[1]:
            continue
        before = clean[:hit.start()].rstrip()
        # inside another macro a use follows the `{` or `;` of its body, or the `do` of a wrapper
        if not before or before[-1] not in ';{}\\':
            return None
        arguments = re.match(r'\s*\(', clean[hit.end():])
        closing = close(clean, hit.end() + arguments.end() - 1, '(', ')') if arguments else None
        tail = re.match(r'[ \t\\\n]*;', clean[closing:]) if closing else None
        if not tail or re.match(r'[ \t\\\n]*;\s*else\b', clean[closing:]):
            return None
        found.append((hit.start(), closing + tail.end()))
    return found


def usable(body):
    return not CONTROL.search(_blank(body))


def unwrap_variants(source, name, header=''):
    clean = _blank(source)
    part = view(source, name)
    macro_edits = []
    for macro in macros(source):
        if macro['kind'] == 'wrapped' and usable(macro['body']) and uses(clean, macro['name'], macro['define']) is not None:
            macro_edits.append([(*macro['open'], '{'), (*macro['close'], '}')])
    out = [('macro_one_shot_unwrap', edit(source, spans)) for spans in macro_edits[:6]]
    body_edits = []
    if part:
        for wrapper in re.finditer(r'\bdo\s*{', part.clean[part.opening:part.end]):
            opening = part.opening + wrapper.end() - 1
            end = close(part.clean, opening, '{', '}')
            tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', part.clean[end:]) if end else None
            if tail and usable(part.clean[opening + 1:end - 1]):
                body_edits.append([(part.opening + wrapper.start(), opening, ''), (end, end + tail.end(), '')])
    together = [span for spans in macro_edits for span in spans]
    inside = [span for spans in body_edits for span in spans]
    if len(macro_edits) > 1:
        out.append(('macro_one_shot_unwrap', edit(source, together)))
    if len(body_edits) > 1:
        out.append(('macro_one_shot_unwrap', edit(source, inside)))
    if macro_edits and body_edits:
        out.append(('macro_one_shot_unwrap', edit(source, together + inside)))
    return list(dict.fromkeys(out))


def rewrap_variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    sites = []
    for macro in macros(source):
        if macro['kind'] != 'braced' or not usable(macro['body']):
            continue
        found = uses(clean, macro['name'], macro['define'])
        if found is None:
            continue
        sites += [(a, b) for a, b in found if part.opening < a < part.end and not re.search(r'\bdo\s*{\s*$', clean[:a])]
    sites = sorted(set(sites))[:SITES]
    out = []
    for count in (1, 2):
        for chosen in itertools.combinations(sites, count):
            out.append(('macro_one_shot_rewrap', edit(source, [(a, b, 'do { ' + source[a:b] + ' } while (0);') for a, b in chosen])))
    return out[:LIMIT]


def variants(source, name, header=''):
    return unwrap_variants(source, name, header) + rewrap_variants(source, name, header)
