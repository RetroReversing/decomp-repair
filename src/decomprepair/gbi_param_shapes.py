"""The shapes around `gbi_macro_param_cursor`'s macros that its straight rewrite of an m2c draft leaves as m2c wrote them.

m2c names a parameter `argN` for the N-th argument word and leaves out the ones the function never reads, so every
stack argument after a gap is loaded from a lower offset than the target's. It also keeps a narrow parameter as `s32`
with its extensions spelled at each use (`(s16) arg7`, `(s32) (arg8 << 0x10) >> 0xE`, `arg1 & 0xFFFF` into a temporary)
where gcc 2.7.2 loaded the word and extended it once, because the parameter was declared `s16`/`u16`; and it names
sums (`temp_t0 = temp_t4 + 0xD`) the original passed to the macro as an expression. This writes those back: the
missing parameters, the widths, the sums in place, 16-bit masked locals as `u16`, and the display list cursor read
before the values the macros use.

On a family of five N64 text-glyph builders (KMC gcc 2.7.2, -O1, 153 to 208 instructions) these, together with the
macros, took all five m2c drafts to 0 (10750-14827; 1465-4208 with the macros alone). No single step reaches it, so the
finished source is offered as one child. Each rewrite reads the same bits as the draft did. A wrapper brace that splits
the command run (`do { ... } while (0);`, a bare block), which leaves the macro rewrite nothing to write over, is
opened first.
"""
import re

from . import gbi_macro_commands, scaffold_strip
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'gbi_param_shapes'
FAMILIES = (FAMILY,)
BLOCK = re.compile(rf'\{{ Gfx \*(?P<local>{IDENT}) = \(\*\(Gfx \*\*\) (?P<param>{IDENT})\);')
SCALAR = r'(?:s32|u32|int)'
ARGUMENT = re.compile(r'arg(\d+)')


def _signature(source, name):
    part = view(source, name)
    if not part:
        return None
    close = part.clean.rfind(')', 0, part.opening)
    depth = 0
    for i in range(close, -1, -1):
        depth += part.clean[i] == ')'
        depth -= part.clean[i] == '('
        if depth == 0:
            return part, i + 1, close
    return None


def _fill_gaps(source, name):
    """`(s32 arg0, s32 arg2)` as `(s32 arg0, s32 arg1, s32 arg2)`: m2c's `argN` is the N-th argument word."""
    found = _signature(source, name)
    if not found:
        return source
    _, start, end = found
    params, out, following = [p.strip() for p in source[start:end].split(',')], [], 0
    for param in params:
        match = re.search(r'\barg(\d+)$', param)
        if not match or int(match[1]) < following or re.search(r'\b(?:f32|f64|float|double|s64|u64)\b', param):
            return source
        number = int(match[1])
        out += [f's32 arg{k}' for k in range(following, number)]
        out.append(param)
        following = number + 1
    return edit(source, [(start, end, ', '.join(out))]) if len(out) > len(params) else source


def _body(source, name):
    part = view(source, name)
    return source[part.opening:part.end]


def _replace_body(source, name, body):
    part = view(source, name)
    return source[:part.opening] + body + source[part.end:]


def _retype(source, name, param, kind):
    found = _signature(source, name)
    _, start, end = found
    text = re.sub(rf'\b{SCALAR}(\s+{param})\b', rf'{kind}\1', source[start:end])
    return source[:start] + text + source[end:]


def _params(source, name):
    found = _signature(source, name)
    if not found:
        return []
    _, start, end = found
    return [m[1] for m in re.finditer(rf'\b{SCALAR}\s+({IDENT})\s*(?:,|$)', source[start:end].strip())]


def _signed_halves(source, name):
    """A word parameter read sign-extended from 16 bits is an `s16` parameter. Its other reads may only be shifted or
    scaled values written into a macro's fields, which keep the low bits the extension leaves alone."""
    for param in _params(source, name):
        body = _body(source, name)
        pair = rf'\(s32\) \({param} << 0x10\) >> '
        read = re.compile(rf'\(s16\) {param}\b|\({pair}(?P<k>0x[0-9A-Fa-f]+|\d+)\)|{pair}(?P<bare>0x[0-9A-Fa-f]+|\d+)')
        hits = list(read.finditer(body))
        if not hits:
            continue
        rest = read.sub('', body)
        low = rf'(?m)^[ \t]*g[DS]P\w+\(.*?[(,] ?{param} (?:<<|\*) (?:0x[0-9a-fA-F]+|\d+)[,)]'
        if len(re.findall(rf'\b{param}\b', rest)) != len(re.findall(low, rest)):
            continue

        def value(m, param=param):
            count = m['k'] or m['bare']
            shift = int(count, 0) - 16 if count else 0
            if shift == 0:
                return param
            return f'({param} * {1 << -shift})' if shift < 0 else f'({param} >> {shift})'
        source = _replace_body(source, name, read.sub(value, body))
        source = _retype(source, name, param, 's16')
    return source


def _assignments(body, local):
    return re.findall(rf'(?<![\w.>]){local}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body)


def _substitute(body, local, text):
    """Drop `local`'s one assignment line and its declaration, and write `text` where it was read."""
    body = re.sub(rf'\n[ \t]*{local}\s*=(?!=)[^;]*;', '', body, count=1)
    body = re.sub(rf'\n[ \t]*{SCALAR}\s+{local}\s*;', '', body)
    return re.sub(rf'(?<![\w.>])({local})\b', text, body)


def _unsigned_halves(source, name):
    """`temp = arg1 & 0xFFFF;`: a `u16` parameter when the macros are its only readers, else `arg1 &= 0xFFFF;`."""
    for param in _params(source, name):
        body = _body(source, name)
        copies = re.findall(rf'(?<![\w.>])({IDENT})\s*=\s*{param} & 0xFFFF\s*;', body)
        if len(copies) != 1 or len(re.findall(rf'\b{param}\b', body)) != 1:
            continue
        local = copies[0]
        if len(_assignments(body, local)) != 1:
            continue
        computed = any(re.search(rf'\b{local}\b', m[1]) for m in re.finditer(rf'(?<![\w.>]){IDENT}\s*=(?!=)([^;]*);', body))
        if computed:
            body = re.sub(rf'(?<![\w.>]){local}\s*=\s*{param} & 0xFFFF\s*;', f'{param} &= 0xFFFF;', body)
            body = re.sub(rf'\n[ \t]*{SCALAR}\s+{local}\s*;', '', body)
            source = _replace_body(source, name, re.sub(rf'(?<![\w.>]){local}\b', param, body))
        else:
            source = _replace_body(source, name, _substitute(body, local, param))
            source = _retype(source, name, param, 'u16')
    return source


def _narrow_locals(source, name):
    """A word local assigned once with a value masked to 16 bits or fewer is a `u16`."""
    body = _body(source, name)
    for found in list(re.finditer(rf'\n[ \t]*{SCALAR}\s+({IDENT})\s*;', body)):
        local = found[1]
        body = _body(source, name)
        values = re.findall(rf'(?<![\w.>]){local}\s*=(?!=)\s*([^;]+);', body)
        if len(values) != 1 or len(_assignments(body, local)) != 1:
            continue
        masked = re.fullmatch(r'(?P<e>.+) & (?P<k>0[xX][0-9a-fA-F]+)', values[0])
        if not masked or int(masked['k'], 16) > 0xFFFF or not gbi_macro_commands._primary(masked['e']):
            continue
        if int(masked['k'], 16) == 0xFFFF:
            inner = gbi_macro_commands._strip(masked['e'])
            body = re.sub(rf'(?<![\w.>])({local}\s*=\s*)[^;]+;', lambda m, inner=inner: f'{m[1]}{inner};', body, count=1)
        body = re.sub(rf'\b{SCALAR}(\s+{local}\s*;)', r'u16\1', body, count=1)
        source = _replace_body(source, name, body)
    return source


def _settled(source, name, read, local):
    """A value that is the same where `local` is read as where it was assigned, and as signed there as in `local`."""
    body = _body(source, name)
    assigned = [m.start() for m in re.finditer(rf'(?<![\w.>]){read}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body)]
    own = re.search(rf'(?<![\w.>]){local}\s*=(?!=)', body)
    return len(assigned) <= 1 and not any(at > own.start() for at in assigned) \
        and not re.search(rf'\b(?:u32|unsigned(?: int)?)\s+{read}\b', source)


def _sums_in_place(source, name):
    """`temp = x + 0xD;` (or `(a + b) - 1`) read by the macros: the sum was the macro's argument."""
    term = rf'(?:{IDENT}|0[xX][0-9a-fA-F]+|\d+)'
    total = rf'\(*{term}(?:\)*\s*(?:\+|-|>>)\s*\(*{term})+\)*'
    for local, value in re.findall(rf'\n[ \t]*({IDENT})\s*=\s*({total})\s*;', _body(source, name)):
        body = _body(source, name)
        if not re.search(rf'\n[ \t]*{SCALAR}\s+{local}\s*;', body) or len(_assignments(body, local)) != 1:
            continue
        reads = re.findall(IDENT, re.sub(r'\b0[xX][0-9a-fA-F]+', '', value))
        if local in reads or not all(_settled(source, name, read, local) for read in reads):
            continue
        value = re.search(rf'\n[ \t]*{local}\s*=\s*([^;]+);', body)[1].strip()  # as the earlier sums left it
        if not re.search(rf'\b{local}\b', body[body.find('{ Gfx *'):]):
            continue
        text = value if gbi_macro_commands._wrapped(value) else f'({value})'
        source = _replace_body(source, name, _substitute(body, local, text))
    body = _body(source, name)  # `(width - 1) + 1`, the image's width read back from its width field
    return _replace_body(source, name, re.sub(rf'\(\(?({IDENT}(?: >> \d+)?)\)? - 1\) \+ 1(?=[,)])', r'\1', body))


def _sdk_line(source, name):
    """A tile loaded from `s` to `(s + width) - 1`: `gDPLoadTextureTile` computes its line from those two edges, so
    write the line as `(((lrs - uls + 1) + 7) >> 3)` (`>> 1` first for 4-bit texels). It folds to the same value, but
    the original expression costs an eight-byte stack slot on gcc 2.7.2."""
    body = _body(source, name)
    for load in re.finditer(rf'gDPLoadTile\([^;]*?, ({IDENT}) \* [24], [^;]*?, \(\(\1 \+ ({IDENT})\) - 1\) \* [24], ', body):
        low, width = load[1], load[2]
        whole = f'(((({low} + {width}) - 1) - {low}) + 1)'
        for found, line in ((rf'\(s32\) \({width} \+ 7\) >> 3', f'(({whole} + 7) >> 3)'),
                            (rf'\(s32\) \(\({width} >> 1\) \+ 7\) >> 3', f'((({whole} >> 1) + 7) >> 3)')):
            body = re.sub(found, lambda _, line=line: line, body)
    return _replace_body(source, name, body)


def _cursor_first(source, name):
    """The block that copies the cursor opens before the values computed for it."""
    body = _body(source, name)
    block = BLOCK.search(body)
    if not block:
        return source
    if re.search(rf'(?<![\w.>*]){block["param"]}\s*[&|^+-]?=(?!=)', body):
        return source
    lead = re.search(rf'(?:(?:\n[ \t]*)+{IDENT}\s*&?=(?!=)(?:(?!->|\*\(|\(\*)[^;])*;)+(?=(?:\n[ \t]*)+\{{ Gfx \*)', body)
    if not lead or lead.end() > block.start():
        return source
    line = body.rfind('\n', 0, block.start())
    body = body[:lead.start()] + body[line:block.end()] + lead[0] + body[block.end():]
    return _replace_body(source, name, body)


def finish(source, name):
    """[finished sources] for a source `gbi_macro_param_cursor` wrote; the fullest first."""
    part = view(source, name)
    if not part or not BLOCK.search(source[part.opening:part.end]) \
            or re.search(r'\b(?:if|else|for|while|do|switch|goto)\b', part.clean[part.opening:part.end]):
        return []
    widened = _signed_halves(_fill_gaps(source, name), name)
    narrowed = _narrow_locals(_unsigned_halves(widened, name), name)
    summed = _sums_in_place(narrowed, name)
    shaped = _cursor_first(summed, name)
    return [text for text in dict.fromkeys((_sdk_line(shaped, name), shaped, widened)) if text != source]


def _flat(source, name):
    """The function with its wrappers opened: a `do { ... } while (0);` or bare block that declares nothing splits the
    command run, so the macros are never written over it. None when there is no wrapper."""
    part = view(source, name)
    if not part:
        return None
    text = scaffold_strip.plain(source, name) or source
    while True:
        part = view(text, name)
        edits = []
        for opening in re.finditer(r'(?<=[;{}])\s*\{', part.clean[part.opening:part.end]):
            start = part.opening + opening.end() - 1
            end = close(part.clean, start, '{', '}') - 1
            inner = part.clean[start + 1:end]
            if part.clean[end:end + 1] == '}' and '{' not in inner and not re.search(rf'(?m)^[ \t]*(?:{IDENT}\s+)+\**\s*{IDENT}\s*;', inner):
                edits = [(start, start + 1, ''), (end, end + 1, '')]
                break
        if not edits:
            return text if text != source else None
        text = edit(text, edits)


def variants(source, name, header=''):
    found = _signature(source, name)
    if not found or not gbi_macro_commands.PARAMETER.search(source, found[1], found[2] + 1):
        return []  # only a display list cursor passed by address
    flat = _flat(source, name)
    drafts = [source] + [text for start in (source, flat) if start for family, text in
                         gbi_macro_commands.variants(start, name, header)
                         if family == gbi_macro_commands.PARAMETER_FAMILY]
    out = dict.fromkeys(text for draft in drafts for text in finish(draft, name))
    return [(FAMILY, text) for text in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
