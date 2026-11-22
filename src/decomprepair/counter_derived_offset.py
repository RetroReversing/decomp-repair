"""A byte offset stepped beside a loop counter, written off the counter (GCC 2.7.2, KMC, N64).

m2c keeps the scaled index of a table walk as its own variable, stepped with the counter:

    s32 offset = 0;
    for (i = 0; i < n; i++, offset += 4)
    {
        p = *((char **) (((char *) table) + offset));

The explicit `offset` is initialised before the loop's guard, so its `move $rN,$zero` is emitted there and lives
while the loop's hoisted conversions (a parameter's zero-extend, set in the preheader) are still being made. When
the table is indexed by the counter instead, `*(char **)((char *) table + (i << 2))`, GCC's loop pass makes the
`i * 4` induction variable itself and initialises it after the hoisted invariants. The register of an incoming
stack byte (the fifth argument, loaded at entry) then no longer overlaps the offset's and goes where the target has
it. A 86-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) went 115 -> 20 with this edit alone
and to 0 with `one_shot_unwrap` on top; written `i * 4` it was 790 (cse folds the product into a stepped pointer), so
the shift form comes first. A candidate rewrite; the exact judge decides.

`counter_derived_offset_unwrapped` is the same edit with every `do { ... } while (0);` wrapper of the function
removed in the same child (the edit `one_shot_unwrap` makes alone): in that function the unwrap alone was 190, worse
than the 115 it started from, and only after the offset edit did it give 0. One child holds both so a search that
judges one step at a time doesn't have to pass through the 20 first.

m2c's own draft spells the same walk as a `do { ... } while` loop with both steps at its end, `var_s0 += 1;
var_s1 += 4;`, the two set to 0 beforehand (draft-cleanup measurement: no m2c draft of 90 had the agent's `for`, so
the family never fired on one). The m2c form is rewritten the same way when the offset's every read is inside the
loop and before both steps (so it always equals counter * K), both start at 0 on every path into the loop, and
both are 32-bit integers; the read is cast to the offset's own type when the counter's differs, value for value.
"""
import re

from .integer_repair_support import NUMBER, edit, view
from .line_scan import lines
from .pattern_repairs import close

FAMILY = 'counter_derived_offset'
UNWRAPPED = 'counter_derived_offset_unwrapped'
FAMILIES = (FAMILY, UNWRAPPED)
_ID = r'[A-Za-z_]\w*'
_DECL = re.compile(rf'^[ \t]*(?:s32|u32|int|unsigned int|u16|s16)[ \t]+(?P<off>{_ID})[ \t]*=[ \t]*0[ \t]*;[ \t]*$')
_FOR = re.compile(
    rf'^(?P<indent>[ \t]*)for[ \t]*\([ \t]*(?P<i>{_ID})[ \t]*=[ \t]*0[ \t]*;(?P<cond>[^;{{}}]*);'
    rf'[ \t]*(?P<step>[^;{{}}]*)\)[ \t]*$')


def _step(text, counter, offset):
    """The constant the offset advances by when `text` is the loop's step clause (counter by 1, offset by a constant)."""
    parts = [p.strip() for p in text.split(',')]
    if len(parts) != 2:
        return None
    one = {f'{counter}++', f'++{counter}', f'{counter} += 1', f'{counter} = {counter} + 1'}
    found = [p for p in parts if p in one]
    other = [p for p in parts if p not in one]
    if len(found) != 1 or len(other) != 1:
        return None
    m = re.fullmatch(rf'{re.escape(offset)}\s*\+=\s*(?P<k>{NUMBER})', other[0])
    return int(m['k'].rstrip('uUlL'), 0) if m else None


def _unwrapped(source, name):
    """`source` with each `do { ... } while (0);` of the function (no break, continue, label or case inside) removed."""
    part = view(source, name)
    if not part:
        return None
    edits = []
    for wrapper in re.finditer(r'\bdo\s*\{', part.clean[part.opening + 1:part.end]):
        start = part.opening + 1 + wrapper.start()
        end = close(part.clean, part.opening + 1 + wrapper.end() - 1, '{', '}')
        tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', part.clean[end:]) if end else None
        inner = part.clean[part.opening + 1 + wrapper.end():end - 1] if end else ''
        if not tail or re.search(r'\b(?:break|continue|goto|case|default|do)\b|\b\w+\s*:(?!:)', inner):
            continue
        edits += [(start, part.opening + 1 + wrapper.end(), ''), (end - 1, end + tail.end(), '')]
    return edit(source, edits) if edits else None


_INT32 = {'s32': 's32', 'int': 's32', 'signed int': 's32', 'M2C_UNK': 's32', 'M2C_UNK32': 's32',
          'u32': 'u32', 'unsigned int': 'u32', 'unsigned': 'u32'}
_M2C_STEPS = (re.compile(rf'(?P<i>{_ID})\s*\+=\s*1\s*;\s*(?P<off>{_ID})\s*\+=\s*(?P<k>{NUMBER})\s*;\s*}}\s*while\s*\('),
              re.compile(rf'(?P<off>{_ID})\s*\+=\s*(?P<k>{NUMBER})\s*;\s*(?P<i>{_ID})\s*\+=\s*1\s*;\s*}}\s*while\s*\('))


def _type(clean, ident):
    m = re.search(rf'^[ \t]*((?:unsigned|signed)\s+int|unsigned|\w+)[ \t]+{re.escape(ident)}[ \t]*;', clean, re.M)
    return _INT32.get(m[1]) if m else None


def _assigned(text, ident):
    v = re.escape(ident)
    return re.search(rf'(?<![\w.>]){v}\s*(?:=(?!=)|[-+*/|&^%]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{v}\b|&\s*{v}\b', text)


def _m2c_loops(source, name, part):
    """The m2c `do { ... counter += 1; offset += K; } while (...)` walks, each read of offset as the counter."""
    clean, out = part.clean, []
    for steps in (hit for pattern in _M2C_STEPS for hit in pattern.finditer(clean, part.opening, part.end)):
        counter, offset, k = steps['i'], steps['off'], int(steps['k'].rstrip('uUlL'), 0)
        if counter == offset or not 0 < k <= 0x10000:
            continue
        # the `do {` this end closes: walk back to its opening brace
        depth, at = 0, steps.end() - len(steps.group(0)) + steps.group(0).rindex('}')
        while at > part.opening:
            depth += {'}': 1, '{': -1}.get(clean[at], 0)
            if depth == 0:
                break
            at -= 1
        do = re.search(r'\bdo\s*$', clean[part.opening:at])
        if depth or not do:
            continue
        loop_start, body_start, body_end = part.opening + do.start(), at + 1, steps.start()
        types = _type(clean[part.opening:part.end], counter), _type(clean[part.opening:part.end], offset)
        if None in types:
            continue
        inner = clean[body_start:body_end]
        mention = rf'(?<![\w.>]){re.escape(offset)}\b'
        reads = [body_start + m.start() for m in re.finditer(mention, inner)]
        if not reads or _assigned(inner, offset) or _assigned(inner, counter) \
                or re.search(r'\b(?:continue|goto|case|default)\b|^\s*\w+\s*:(?!:)', inner, re.M):
            continue
        cond_end = close(clean, steps.end() - 1)
        if not cond_end or re.search(mention, clean[steps.end():part.end]):
            continue
        # both set to 0 before the loop, in blocks still open at the `do`, with nothing between that jumps or sets them
        before = clean[part.opening + 1:loop_start]
        inits = {}
        for ident in (counter, offset):
            found = list(re.finditer(rf'(?<![\w.>]){re.escape(ident)}\s*=\s*0\s*;', before))
            if not found:
                break
            inits[ident] = found[-1]
        if len(inits) != 2:
            continue
        first = min(m.start() for m in inits.values())
        between = before[first:]
        if re.search(r'\b(?:goto|while|for|return|break|continue)\b|^\s*\w+\s*:(?!:)', between, re.M):
            continue
        if any(_assigned(before[m.end():], ident) for ident, m in inits.items()):
            continue
        declaration = rf'(?m)^[ \t]*(?:(?:un)?signed\s+)?\w+[ \t]+{re.escape(offset)}[ \t]*;'
        if re.search(mention, re.sub(declaration, '', before[:inits[offset].start()])):
            continue
        depth, low = 0, 0
        for ch in between:
            depth += {'{': 1, '}': -1}.get(ch, 0)
            low = min(low, depth)
        if low < 0:
            continue
        init = _line(source, part.opening + 1 + inits[offset].start(), part.opening + 1 + inits[offset].end())
        step_at = steps.start('off')
        step = _line(source, step_at, clean.index(';', step_at) + 1)
        spellings = [f'({counter} << {k.bit_length() - 1})'] if k & (k - 1) == 0 else []
        spellings.append(f'({counter} * {k})')
        for spelling in spellings:
            if types[0] != types[1]:
                spelling = f'(({types[1]}) {spelling})'
            edits = [(*init, ''), (*step, '')] + [(at, at + len(offset), spelling) for at in reads]
            out.append((FAMILY, edit(source, edits)))
    return out


def _line(source, start, end):
    """The span of a statement to remove: its whole line when nothing else is on it."""
    head = source.rfind('\n', 0, start) + 1
    tail = source.find('\n', end)
    tail = len(source) if tail < 0 else tail + 1
    if not source[head:start].strip() and not source[end:tail].strip():
        return head, tail
    return start, end


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = _m2c_loops(source, name, part)
    for index in range(1, len(body)):
        loop = _FOR.fullmatch(body[index].stripped)
        decl = _DECL.fullmatch(body[index - 1].stripped)
        if not loop or not decl or index + 1 >= len(body) or body[index + 1].stripped != '{':
            continue
        counter, offset = loop['i'], decl['off']
        k = _step(loop['step'], counter, offset)
        if not k or counter == offset:
            continue
        stop = close(part.clean, body[index + 1].start + body[index + 1].text.index('{'), '{', '}')
        if stop is None:
            continue
        inner = part.clean[body[index + 1].end:stop - 1]
        rest = part.clean[part.opening:body[index - 1].start] + part.clean[stop:part.end]
        mention = rf'(?<![\w.>]){re.escape(offset)}\b'
        # the offset is the loop's alone: not read before or after it, and the counter is only stepped by the header
        if re.search(mention, rest) or re.search(mention+r'\s*(?:=(?!=)|[-+*/|&^]=|\+\+|--)', inner) \
                or re.search(rf'&\s*{re.escape(offset)}\b', inner):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(counter)}\b\s*(?:=(?!=)|[-+*/|&^]=|\+\+|--)', inner) \
                or re.search(rf'(?:\+\+|--)\s*{re.escape(counter)}\b|&\s*{re.escape(counter)}\b', inner):
            continue
        if not re.search(mention, inner):
            continue
        spellings = []
        if k & (k - 1) == 0:
            spellings.append(f'({counter} << {k.bit_length() - 1})')
        spellings.append(f'({counter} * {k})')
        for spelling in spellings:
            edits = [(body[index - 1].start, body[index - 1].end, ''),
                     (body[index].start, body[index].end,
                      f'{loop["indent"]}for ({counter} = 0;{loop["cond"]}; {counter}++)\n')]
            for m in re.finditer(mention, inner):
                at = body[index + 1].end + m.start()
                edits.append((at, at + len(offset), spelling))
            child = edit(source, edits)
            out.append((FAMILY, child))
            unwrapped = _unwrapped(child, name)
            if unwrapped:
                out.append((UNWRAPPED, unwrapped))
    return out
