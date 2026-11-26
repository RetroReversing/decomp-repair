"""A call's narrowing conversions evaluated before the statement that sets the call's pointer argument.

A table row's address is set in a local right before the call that takes it, and the call's other arguments convert
floats on the way in (`s = TABLE[i]; q = make((u16) (u32) cx, (u16) (u32) cy, s, i);`). Written like that the
conversions are evaluated after the address, so the address's `lui`/`addiu` and the index arithmetic sit before the float
sequences; the target evaluates the conversions first (their `trunc.w.s`/`andi` run, then the row's address, then the call).
Staging each conversion in a local of its own before the address statement gave that order (a 534-instruction panel
builder: 11961 -> 11136 with `u16` locals, then 9151 -> 8971 with `s32` ones, which make the narrowing happen where the
local is set, so the call's argument needs none of its own).

`variants` finds a call statement `[T =] f(ARGS);` whose previous statement is `P = EXPR;` with `P` among the arguments
(EXPR a plain expression: no call, nothing the conversions read), and whose other arguments include conversions of the
shape `(u16|s16|u8|s8) (u32|s32|int) ...`. Each such argument becomes a local `staged_arg<N>` (declared `s32` at the top of the
function) set right before `P = EXPR;`. Two children: `s32` locals and locals of the conversion's own narrow type."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'call_conversion_stage'
FAMILIES = (FAMILY,)
CONVERSION = re.compile(r'^\(\s*(u16|s16|u8|s8)\s*\)\s*\(\s*(?:u32|s32|int|unsigned(?:\s+int)?)\s*\)\s*\S')
CALL = re.compile(r'(?m)^([ \t]*)(?:([A-Za-z_]\w*)\s*=\s*)?([A-Za-z_]\w*)\s*\(')
PREVIOUS = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*([^;{}]+);[ \t]*\n[ \t]*$')


def _python_split(text):
    parts, depth, last = [], 0, 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0 and char == ',':
            parts.append(text[last:at])
            last = at + 1
    parts.append(text[last:])
    return parts


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text):
        return _scan.top_pieces(text, ',', 1)


def variants(source, name):
    span = find(source, name)
    if not span or 'staged_arg0' in source:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    edits = []
    for hit in CALL.finditer(clean, opening, span[1]):
        if hit[3] in ('if', 'for', 'while', 'switch', 'return', 'sizeof'):
            continue
        open_at = hit.end() - 1
        stop = close(clean, open_at)
        if not stop or clean[stop:stop + 1] != ';':
            continue
        args = _split(source[open_at + 1:stop - 1])
        before = clean[opening:hit.start()]
        last = re.search(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*([^;{}]+);[ \t]*\n\s*$', before)
        if not last or last.end() != len(before):
            continue
        pointer, expr = last[2], last[3]
        names = [part.strip() for part in args]
        if pointer not in names or re.search(r'\w\s*\(', expr):
            continue
        staged = [(index, part.strip()) for index, part in enumerate(args)
                  if CONVERSION.match(part.strip()) and not re.search(rf'(?<![\w.]){re.escape(pointer)}\b', part)]
        if not staged:
            continue
        edits.append((opening + last.start(), hit.start(), open_at, stop, args, staged, last[1]))
        break
    if not edits:
        return []
    out = []
    for narrow in (False, True):
        text = source
        for line_at, call_at, open_at, stop, args, staged, indent in reversed(edits):
            names = {index: f'staged_arg{n}' for n, (index, _) in enumerate(staged)}
            new_args = [(' ' + names[i] if i in names and part.startswith(' ') else names.get(i, part)) for i, part in enumerate(args)]
            text = text[:open_at + 1] + ','.join(new_args) + text[stop - 1:]
            lines = ''.join(f'{indent}{names[index]} = {arg};\n' for index, arg in staged)
            text = text[:line_at] + lines + text[line_at:]
            decl = ''.join(f'    {re.match(r"[(](u16|s16|u8|s8)", arg)[1] if narrow else "s32"} {names[index]};\n' for index, arg in staged)
            line = text.find('\n', opening) + 1
            text = text[:line] + decl + text[line:]
        out.append(text)
    return [(FAMILY, text) for text in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 66}
