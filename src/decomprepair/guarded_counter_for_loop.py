"""A counted loop m2c wrote as a guarded `do { } while`, written as the `for` loop the game had (GCC 2.7.2, KMC, N64).

m2c turns a counted loop into `i = 0; ... if (n > 0) { do { body; i += 1; } while (i < n); }`, and a saved best that was
searched from it often keeps the guard's count behind an identity helper (`inline static s32 count_of(void *p) {
return (s32) p->count; }`, `if (count_of(p) > 0)`). The game's `for (i = 0; i < n; i++)` compiles differently in two
ways that the guarded form can't give:

 - jump.c copies a loop's top test in front of the loop only for a `for`/`while`; the copy (a `slt` into a pseudo
   that the combine pass folds into `blez`) leaves pseudo registers that a later pass still counts, and each one
   claims a slot of the frame's spill area (reload.c assigns one for every pseudo with references, and a frame 8 bytes
   short was the sign of the loop having none); and
 - the counter's references: the plain bound read in the test is one reference more in the loop than the helper's
   call left, so the counter ranks above the loop's strength-reduced multiples (`i * 3`, `i * 6`) for the saved
   register that the arguments' copy needs (global.c orders by floor_log2(refs) * refs / live length).

On a 529-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) this step was 1486 -> 500 after the
stepped locals had been written as the counter's multiples (`volatile_step_index`), and the frame's spill slots then
all matched. The helper is read from the source (a one-line `return` of an expression of its parameter) and the guard
is used only when it is the same value as the loop's bound, so the `for` runs exactly the iterations the guard and the
`do` did; the early `counter = 0;` that only this loop reads goes into the `for`. A candidate rewrite; the exact judge
decides.

`volatile_step_for_loop` is the whole chain from a saved best that stood the loop's stepped cursors in `volatile`
locals, as one child: `volatile_step_index` (the cursors as the counter's multiples), the identical-arm guards that are
left around the multiples written once (the same source line twice, one per arm of a guard on an unrelated global), and
this family's `for` loop. The steps are 1263, 1486 and 500 for a function that started at 922 (the first two are worse
than where they started and the last better than all of them: a greedy chain stops at the first), so it is offered
whole.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_counter_for_loop'
STEPPED = 'volatile_step_for_loop'
FAMILIES = (FAMILY, STEPPED)
MAX_COMBINED = 6
_IF = re.compile(r'\bif\s*\(')
_HELPER = re.compile(rf'(?:\binline\s+static|\bstatic\s+inline|\bstatic)\s+[\w\s*]+?\b(?P<name>{IDENT})\s*\(\s*(?:[\w\s*]+?[\s*])?'
                     rf'(?P<param>{IDENT})\s*\)\s*\{{\s*return\s+(?P<body>[^;{{}}]+);\s*\}}')
_STEP = re.compile(rf'(?P<head>[\s\S]*?)(?P<step>(?<![\w.>])(?:(?P<a>{IDENT})\s*\+=\s*1|(?P<b>{IDENT})\s*=\s*(?P=b)\s*\+\s*1|'
                   rf'(?P<c>{IDENT})\+\+|\+\+(?P<d>{IDENT}))\s*;)\s*$')


def _plain(text):
    """`text` without spaces, `(s32)` casts, parentheses around a lone name or the whole: the comparable form."""
    text = re.sub(r'\s+', '', text).replace('(s32)', '')
    while True:
        before = text
        text = re.sub(rf'\(({IDENT})\)', r'\1', text)
        if text.startswith('(') and close(text, 0) == len(text):
            text = text[1:-1]
        if text == before:
            return text


def _helpers(clean):
    return {m['name']: (m['param'], m['body']) for m in _HELPER.finditer(clean)}


def _value(text, helpers):
    """The comparable form of a guard's count: a call of a one-expression helper is its body with the argument put in."""
    text = text.strip()
    call = re.fullmatch(rf'(?P<f>{IDENT})\s*\((?P<arg>[^(),]*(?:\([^()]*\)[^(),]*)*)\)', text)
    if call and call['f'] in helpers:
        param, body = helpers[call['f']]
        text = re.sub(rf'(?<![\w.>]){re.escape(param)}\b', lambda _: '(' + call['arg'].strip() + ')', body)
    return _plain(text)


def variants(source, name, header='', only=None):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    helpers = _helpers(clean[:part.opening])
    out = []
    for guard in _IF.finditer(clean, part.opening + 1, part.end):
        paren = close(clean, guard.end() - 1)
        if not paren:
            continue
        condition = clean[guard.end():paren - 1]
        count = re.fullmatch(r'(?P<lhs>[\s\S]+?)\s*>\s*0', condition)
        block = re.match(r'\s*\{', clean[paren:])
        if not count or not block:
            continue
        open_at = paren + block.end() - 1
        shut = close(clean, open_at, '{', '}')
        if not shut:
            continue
        inside = clean[open_at + 1:shut - 1]
        do = re.match(r'\s*do\s*\{', inside)
        if not do:
            continue
        body_open = open_at + 1 + do.end() - 1
        body_end = close(clean, body_open, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[body_end:shut - 1]) if body_end else None
        if not tail:
            continue
        cond_open = body_end + tail.end() - 1
        cond_end = close(clean, cond_open)
        if not cond_end or clean[cond_end:shut - 1].strip() != ';':
            continue
        compare = re.fullmatch(rf'\s*(?P<c>{IDENT})\s*<\s*(?P<bound>[\s\S]+)', clean[cond_open + 1:cond_end - 1])
        if not compare:
            continue
        counter, bound = compare['c'], compare['bound']
        if _value(count['lhs'], helpers) != _plain(bound):
            continue
        body = clean[body_open + 1:body_end - 1]
        step = _STEP.fullmatch(body)
        if not step or (step['a'] or step['b'] or step['c'] or step['d']) != counter:
            continue
        head = step['head']
        if re.search(r'\b(?:continue|goto|case|default)\b|^\s*\w+\s*:(?!:)', head, re.M) \
                or re.search(rf'(?<![\w.>]){re.escape(counter)}\s*(?:=(?!=)|[-+*/|&^%]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{re.escape(counter)}\b|&\s*{re.escape(counter)}\b', head):
            continue
        # the counter starts at 0 before the guard, and nothing else in between reads it
        starts = list(re.finditer(rf'(?<![\w.>]){re.escape(counter)}\s*=\s*0\s*;', clean[part.opening + 1:guard.start()]))
        if not starts:
            continue
        at = part.opening + 1 + starts[-1].start()
        stop = part.opening + 1 + starts[-1].end()
        if re.search(rf'(?<![\w.>]){re.escape(counter)}\b', clean[stop:guard.start()]):
            continue
        if re.search(rf'\bfor\s*\([^)]*{re.escape(counter)}', clean[stop:guard.start()]):
            continue
        original = source[body_open + 1:body_end - 1]
        keep = original[:len(step['head'])]
        replacement = f'for ({counter} = 0; {counter} < {source[cond_open + 1:cond_end - 1].split("<", 1)[1].strip()}; {counter}++)\n' \
                      f'{_indent(source, guard.start())}{{{keep.rstrip()}\n{_indent(source, guard.start())}}}'
        out.append((FAMILY, edit(source, [(at, stop, ''), (guard.start(), shut, replacement)])))
    if only is None:
        out += _chain(source, name, header)
    return out


def _chain(source, name, header):
    from . import identical_arm_collapse_repairs, volatile_step_index
    out = []
    starts = [text for _, text in volatile_step_index.variants(source, name, header)] or [source]
    for start in starts:
        collapsed = [text for _, text in identical_arm_collapse_repairs.variants(start, name, header)] or [start]
        for text in collapsed:
            out += [(STEPPED, child) for _, child in variants(text, name, only=FAMILY)]
        if len(out) >= MAX_COMBINED:
            break
    return list(dict.fromkeys(out))[:MAX_COMBINED]


def _indent(source, at):
    return re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:])[0]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
