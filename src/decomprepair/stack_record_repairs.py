"""m2c's `spNN` locals that are one record on the stack, and the padding parameter m2c puts before a double.

A function that fills an argument record on its stack and passes its address comes back from m2c as separate
locals, the first one's address passed:

    sp10 = arg0; sp14 = arg1; sp18 = arg2; sp1C = arg3; sp20 = arg4; sp28 = arg6;
    if (g(&sp10) == 0) { ... }
    return sp28;

and its signature as `(s32 arg0, s32 arg1, s32 arg2, s32 arg3, f64 arg4, s32 arg5, f64 arg6)`: m2c reads the
aligned second double's slot as an `s32` and a double after it. An N64 library's math-error wrapper was exact with
the locals as one struct, in offset order, and the unused `s32` before the double left out of the signature (with the
struct alone it was 99.99%: the double was read 8 bytes along).

`stack_argument_record` offers the struct (all `spNN` locals from the passed one upward, in offset order, contiguous
for their sizes); `double_padding_parameter` offers the signature without an unused `s32` parameter just before an
`f64` one.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

RECORD = 'stack_argument_record'
PADDING = 'double_padding_parameter'
FAMILIES = (RECORD, PADDING)

IDENT = r'[A-Za-z_]\w*'
SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'f64': 8, 'void *': 4}


def _record(source, clean, opening, end):
    decls = {m['name']: (m['type'], int(m['off'], 16), m)
             for m in re.finditer(r'(?m)^[ \t]*(?P<type>s8|u8|s16|u16|s32|u32|f32|f64|void \*)\s*(?P<name>sp(?P<off>[0-9A-Fa-f]+))'
                                  r'\s*;[ \t]*\n', clean[opening:end])}
    passed = re.search(r'&\s*(?P<name>sp[0-9A-Fa-f]+)\b', clean[opening:end])
    if not passed or passed['name'] not in decls:
        return None
    base = decls[passed['name']][1]
    fields = sorted((off, typ, name) for name, (typ, off, _) in decls.items() if off >= base)
    at = base
    for off, typ, _ in fields:
        size = SIZES[typ]
        at = (at + size - 1) // size * size
        if off != at:
            return None
        at += size
    # every other mention of the fields is a plain read or write (no further address taken)
    if len(re.findall(r'&\s*sp[0-9A-Fa-f]+\b', clean[opening:end])) != 1:
        return None
    struct = 'struct {\n' + ''.join(f'        {typ} f{off:X};\n' for off, typ, _ in fields) + '    } __repair_frame;\n'
    text = source[opening:end]
    for _, _, name in fields:
        text = re.sub(r'(?m)^[ \t]*(?:s8|u8|s16|u16|s32|u32|f32|f64|void \*)\s*' + name + r'\s*;[ \t]*\n', '', text, count=1)
    text = re.sub(r'&\s*' + passed['name'] + r'\b', '&__repair_frame', text)
    for off, _, name in fields:
        text = re.sub(r'(?<![\w.>])' + name + r'\b', f'__repair_frame.f{off:X}', text)
    text = text.replace('{\n', '{\n    ' + struct, 1)
    # the record's stores in offset order, as the game filled it (m2c lists the first field's store last)
    run = re.search(r'(?:^[ \t]*__repair_frame\.f[0-9A-F]+ = [^;\n]*;[ \t]*\n){2,}', text, re.M)
    if run:
        lines = run.group(0).splitlines(keepends=True)
        lines.sort(key=lambda line: int(re.search(r'\.f([0-9A-F]+)', line)[1], 16))
        text = text[:run.start()] + ''.join(lines) + text[run.end():]
    return source[:opening] + text + source[end:]


def _padding(source, clean, span, opening, end):
    signature = clean[span[0]:opening]
    params = re.search(r'\((?P<list>[^()]*)\)\s*$', signature)
    if not params:
        return []
    parts = [p.strip() for p in params['list'].split(',')]
    result = []
    for i in range(len(parts) - 1):
        name = re.fullmatch(r's32\s+(' + IDENT + r')', parts[i])
        if not name or not re.fullmatch(r'f64\s+' + IDENT, parts[i + 1]):
            continue
        if re.search(r'(?<![\w.>])' + name[1] + r'\b', clean[opening:end]):
            continue
        kept = parts[:i] + parts[i + 1:]
        at = span[0] + params.start('list')
        text = source[:at] + ', '.join(kept) + source[span[0] + params.end('list'):]
        result.append(text)
    return result


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    record = _record(source, clean, opening, end)
    if record:
        result.append((RECORD, record))
    for padded in _padding(source, clean, span, opening, end):
        result.append((PADDING, padded))
        if record:
            again = _blank(padded)
            sp2 = find(padded, name)
            o2 = again.find('{', sp2[0], sp2[1])
            e2 = close(again, o2, '{', '}')
            both = _record(padded, again, o2, e2)
            if both:
                result.append((RECORD, both))
    return result[:4]
