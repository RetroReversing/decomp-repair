"""m2c's counted search written back as the `for` loop with a `break` it was, cursor folded into the index.

A search over a small table (`for (i = 0; i < 4; i++) { if (ready[i] == 1) { found = 1; who = i; break; } }`) comes
back from m2c as a label whose found case is the `if`'s own arm, the step and the backward jump in the `else`, and the
table walked by a pointer set before the loop:

    i = 0;
    p = &table;
    other = 0;
    loop_19:
    if (*(s32 *) p == 1) { found = 1; who = i; } else { i += 1; p += 4; if (i < 4U) { goto loop_19; } }

`goto_backward_loop` makes that a `for (;;)` with `continue` and keeps the pointer, one loop at a time. Here every such
loop of the function is written at once:

`counted_search_index_for`
    the cursor read as the table indexed by the counter (`((s32 *) &table)[i]`), its set and step gone; offered for a
    cursor whose only mentions are its declaration, its set, its step and reads inside the loop, each read as wide as
    the step.
`counted_search_cursor_for`
    the same loop with the cursor kept and stepped in the `for` header, the counter's `= 0` left where it was.

Both require the counter set to 0 and the bound a positive literal, so the first pass always runs and the program is
the one given. Matched on a 263-instruction N64 actor update (SN, `-O2 -mips3 -mfp64`) with three such loops: from its
draft the index form went 6855 -> 3180, the cursor form 3980, and `goto_backward_loop` on one loop 5990.

A hypothesis like every family's; the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

INDEX = 'counted_search_index_for'
CURSOR = 'counted_search_cursor_for'
FAMILIES = (INDEX, CURSOR)

_ID = r'[A-Za-z_]\w*'
_WIDTH = {'char': 1, 's8': 1, 'u8': 1, 'short': 2, 's16': 2, 'u16': 2, 'int': 4, 'long': 4, 's32': 4, 'u32': 4,
          'f32': 4, 'float': 4, 'f64': 8, 'double': 8, 's64': 8, 'u64': 8}
_HEAD = re.compile(rf'(?<![\w.>?:])({_ID})\s*:(?!:)\s*if\s*\(')
_STEP = re.compile(rf'\s*(?:({_ID})\s*(?:\+=\s*(0[xX][0-9a-fA-F]+|\d+)[uU]?|(\+\+))|({_ID})\s*=\s*\4\s*\+\s*'
                   rf'(0[xX][0-9a-fA-F]+|\d+)[uU]?)\s*;')
_AGAIN = re.compile(rf'\s*if\s*\(\s*({_ID})\s*(<|!=)\s*(0[xX][0-9a-fA-F]+|\d+)([uU]?)\s*\)\s*(\{{\s*)?goto\s+({_ID})\s*;')


def _braced(clean, at):
    """(inside start, end past the brace) of the block that opens at the next non-blank character, or None."""
    brace = re.compile(r'\s*\{').match(clean, at)
    if not brace:
        return None
    end = close(clean, brace.end() - 1, '{', '}')
    return (brace.end(), end) if end else None


def _loops(clean, opening, end):
    """Each search loop of the shape above, in order."""
    out = []
    for head in _HEAD.finditer(clean, opening, end):
        label = head[1]
        if len(re.findall(rf'\bgoto\s+{label}\s*;', clean)) != 1:
            continue
        paren = head.end() - 1
        stop = close(clean, paren, '(', ')')
        found = stop and _braced(clean, stop)
        if not found:
            continue
        other = re.compile(r'\s*else\b').match(clean, found[1])
        rest = other and _braced(clean, other.end())
        if not rest:
            continue
        at, steps = rest[0], []
        while (step := _STEP.match(clean, at)):
            name = step[1] or step[4]
            steps.append((name, 1 if step[3] else int(step[2] or step[5], 0)))
            at = step.end()
        again = _AGAIN.match(clean, at)
        if not again or again[6] != label:
            continue
        tail = again.end()
        if again[5]:
            brace = re.compile(r'\s*\}').match(clean, tail)
            if not brace:
                continue
            tail = brace.end()
        counter, bound = again[1], int(again[3], 0)
        names = [name for name, _ in steps]
        body = clean[found[0]:found[1] - 1]
        if (clean[tail:rest[1] - 1].strip() or bound < 1 or len(set(names)) != len(names)
                or dict(steps).get(counter) != 1
                or re.search(r'\b(?:goto|break|continue|for|while|do|switch|case)\b', body)):
            continue
        out.append({'label': head.start(1), 'test': (paren + 1, stop - 1), 'found': (found[0], found[1] - 1),
                    'end': rest[1], 'counter': counter, 'steps': steps,
                    'bound': f'{counter} {again[2]} {again[3]}{again[4]}'})
    return out


def _set_before(clean, opening, at, name):
    """(start, end, value) of the last `name = value;` before `at`, when it reaches `at` with nothing in between that
    mentions the name, jumps, or leaves the block it stands in."""
    sets = list(re.finditer(rf'(?m)^[ \t]*{name}\s*=(?!=)\s*([^;{{}}]+);[ \t]*\n', clean[opening:at]))
    if not sets:
        return None
    last = sets[-1]
    start, stop = opening + last.start(), opening + last.end()
    between = clean[stop:at]
    depth = 0
    for char in between:
        depth += {'{': 1, '}': -1}.get(char, 0)
        if depth < 0:
            return None
    if depth or re.search(rf'\b{name}\b|\bgoto\b|(?<![\w.>?:]){_ID}\s*:(?!:)', between):
        return None
    return start, stop, last[1].strip()


def _declared(clean, name):
    """(type name, stars) of the local or global declared as `name`, or None."""
    hit = re.search(rf'(?m)^[ \t]*(?:extern\s+|static\s+)?({_ID})\b[ \t]*(\**)[ \t]*{name}\s*(?:;|\[)', clean)
    return (hit[1], len(hit[2])) if hit else None


def _indexed(source, clean, span, loop, name, step, setting):
    """The cursor's reads in the loop as edits to indexed reads, or None when it is more than a cursor."""
    declared = _declared(clean[span[0]:span[1]], name)
    if not declared:
        return None
    kind, stars = declared
    unit = 1 if not stars else 4 if stars > 1 else _WIDTH.get(kind)
    if unit is None:
        return None
    base = setting[2]
    if not re.fullmatch(rf'&\s*{_ID}(?:\[\w+\])?', base):
        if not re.fullmatch(_ID, base) or not re.search(rf'\b{base}\s*\[', clean[:span[0]]):
            return None
    width = unit * step
    inside = [loop['test'], loop['found']]
    edits = []
    cast = re.compile(rf'\*\s*\(\s*({_ID})\s*(\**)\s*\*\s*\)\s*{name}\b(?!\s*[+\-\[.]|\s*->)')
    plain = re.compile(rf'(?<![\w)\]])(?<![\w)\]]\s)\*\s*{name}\b(?!\s*[+\-\[.]|\s*->)')
    member = re.compile(rf'\b{name}\s*->')
    for start, stop in inside:
        for hit in cast.finditer(clean, start, stop):
            if (4 if hit[2] else _WIDTH.get(hit[1])) != width:
                return None
            kind_read = source[hit.start(1):hit.end(2)].strip()
            edits.append((hit.start(), hit.end(), f'(({kind_read} *) {base})[{loop["counter"]}]'))
        if stars and step == 1:
            element = kind + (' ' + '*' * (stars - 1) if stars > 1 else '')
            for hit in plain.finditer(clean, start, stop):
                edits.append((hit.start(), hit.end(), f'(({element} *) {base})[{loop["counter"]}]'))
            if stars == 1:
                for hit in member.finditer(clean, start, stop):
                    edits.append((hit.start(), hit.end(), f'(({kind} *) {base})[{loop["counter"]}].'))
    mentions = len(re.findall(rf'\b{name}\b', clean[span[0]:span[1]]))
    # the declaration, the set, the step (twice when written `p = p + k`) and the reads rewritten: nothing else
    stepped = len(re.findall(rf'\b{name}\b', clean[loop['found'][1]:loop['end']]))
    if not edits or mentions != 2 + stepped + len(edits):
        return None
    return edits


def _rewrite(source, name, index):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    edits, folded = [], 0
    for loop in _loops(clean, opening, span[1]):
        counter = loop['counter']
        zero = _set_before(clean, opening, loop['label'], counter)
        if not zero or zero[2] not in ('0', '0U', '0u'):
            continue
        header, body = [], []
        for stepped, step in loop['steps']:
            setting = None if stepped == counter else _set_before(clean, opening, loop['label'], stepped)
            reads = (_indexed(source, clean, span, loop, stepped, step, setting)
                     if index and setting else None)
            if reads is None:
                header.append(f'{stepped}++' if step == 1 else f'{stepped} += {step}')
                continue
            folded += 1
            edits.append((setting[0], setting[1], ''))
            body += reads
        if index:
            edits.append((zero[0], zero[1], ''))
        first = f'{counter} = 0' if index else ''

        def spliced(piece, body=body):
            text, at = '', piece[0]
            for start, stop, replacement in sorted(body):
                if piece[0] <= start and stop <= piece[1]:
                    text += source[at:start] + replacement
                    at = stop
            return text + source[at:piece[1]]

        line = source.rfind('\n', 0, loop['label']) + 1
        indented = source.rfind('\n', 0, loop['end'] - 1) + 1
        indent = re.match(r'[ \t]*', source[indented:])[0]
        found = [text.strip() for text in spliced(loop['found']).split('\n') if text.strip()]
        text = (f'{indent}for ({first}; {loop["bound"]}; {", ".join(header)}) {{\n'
                f'{indent}    if ({spliced(loop["test"]).strip()}) {{\n'
                + ''.join(f'{indent}        {part}\n' for part in found)
                + f'{indent}        break;\n{indent}    }}\n{indent}}}')
        edits.append((line, loop['end'], text))
    if not edits or (index and not folded):
        return None
    for start, stop, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[stop:]
    return source


def variants(source, name):
    out = []
    for family, index in ((INDEX, True), (CURSOR, False)):
        text = _rewrite(source, name, index)
        if text:
            out.append((family, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
