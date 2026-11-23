"""A call argument m2c computed one iteration ahead, written as the counter expression at the call.

For a loop whose first call takes the counter masked (`audio_reset(i & 0xFF, slot)`) the compiler rotates the loop: the
argument is computed after the counter's step, in the delay slot of the bottom branch, and once before the loop. m2c
writes that rotation out as a local: `arg = 0 & 0xFF;` above the loop, `call(arg, ...)` in it and `arg = ((s32) i) & 0xFF;`
as its last statement. Compiled as written, the entry value is a constant (`move $a0, $zero`) where the target's entry
copy is the same `andi` the loop repeats (`andi $a0, $s1, 0xff`), 505 -> 305 on a 384-instruction function (isolated
judge; no other family offered a child that moved that score).

For a counter `i` that is set to a number before the loop and stepped in it, and a local `arg` that is set once above the
loop to an expression of numbers, assigned last in the body to an expression of `i`, and read in the body before the
counter's step, the child writes the expression at each read, and drops both assignments. It is checked that the entry
value is the expression's value for the counter's first value (evaluated, not compared as text), so the program is the
same program. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .loop_address_hoist_repairs import _loops
from .pattern_repairs import close

FAMILY = 'loop_argument_inline'
FAMILIES = (FAMILY,)
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
CAST = re.compile(r'\(\s*(?:s8|u8|s16|u16|s32|u32|int|long|unsigned|char|short)\s*\)')


def _value(text, counter=None, number=None):
    """The integer `text` evaluates to (casts ignored, `counter` read as `number`), or None when it is not plain arithmetic."""
    text = CAST.sub('', text)
    if counter is not None:
        text = re.sub(rf'(?<![\w.>]){re.escape(counter)}\b', str(number), text)
    text = re.sub(r'\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b', lambda m: str(int(m[1], 0)), text)
    if not re.fullmatch(r'[\s\d()&|^~+\-*<>]+', text):
        return None
    try:
        return int(eval(text, {'__builtins__': {}}, {}))  # noqa: S307 (digits, operators and hex only, checked above)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    result = []
    for loop in _loops(clean, opening, end):
        text = clean[loop[0]:loop[1]]
        body = re.match(r'do\s*\{', text)
        if not body:
            continue
        body_open = loop[0] + body.end() - 1
        body_end = close(clean, body_open, '{', '}')
        if not body_end:
            continue
        inner = clean[body_open + 1:body_end - 1]
        last = list(re.finditer(rf'(?:^|[;{{}}])\s*(?P<stmt>(?P<arg>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}]+?)\s*;)\s*$', inner))
        if not last:
            continue
        tail = last[-1]
        arg, expr = tail['arg'], tail['expr']
        step = re.search(rf'(?P<c>{IDENT})\s*(?:\+=\s*(?P<k>{NUMBER})|\+\+)\s*;', inner[:tail.start('stmt')])
        if not step:
            continue
        counter = step['c']
        if counter == arg or not re.search(rf'(?<![\w.>]){re.escape(counter)}\b', expr):
            continue
        before = clean[opening:loop[0]]
        preset = list(re.finditer(rf'(?:do\s*\{{\s*)?(?<![\w.>]){re.escape(arg)}\s*=(?!=)\s*(?P<v>[^;{{}}]+?)\s*;(?:\s*\}}\s*while\s*\(\s*0\s*\)\s*;)?\s*$',
                                  before))
        start = list(re.finditer(rf'(?<![\w.>]){re.escape(counter)}\s*=(?!=)\s*(?P<v>{NUMBER})\s*;', before))
        if not preset or not start:
            continue
        first = _value(start[-1]['v'])
        entry = _value(preset[-1]['v'])
        if first is None or entry is None or _value(expr, counter, first) != entry:
            continue
        # the argument is read only in the body, before the counter's step, and nowhere else in the function
        reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(arg)}\b', clean[opening:end])
                 if not re.match(rf'[ \t]*[A-Za-z_][\w ]*[ \t]+{re.escape(arg)}[ \t]*;[ \t]*$',
                                 clean[clean.rfind('\n', 0, opening + m.start()) + 1:clean.find('\n', opening + m.start())])]
        inside = [m for m in reads if body_open < opening + m.start() < body_open + 1 + step.start()]
        if len(reads) != len(inside) + 2 or not inside:
            continue
        edits = [(body_open + 1 + tail.start('stmt'), body_open + 1 + tail.end('stmt'), '')]
        edits += [(opening + m.start(), opening + m.end(), f'({expr})') for m in inside]
        whole = preset[-1]
        wrapper = re.search(r'do\s*\{\s*$', before[:whole.start()])
        first_char = wrapper.start() if wrapper and re.search(r'\}\s*while\s*\(\s*0\s*\)\s*;\s*$', whole.group()) else whole.start()
        edits.append((opening + first_char, opening + whole.end(), ''))
        child = edit(source, edits)
        if child != source and (FAMILY, child) not in result:
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
