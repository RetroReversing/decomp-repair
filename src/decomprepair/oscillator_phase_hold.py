"""Keep computed axes across a witnessed input call and reuse the consumed float."""

import re

from .integer_repair_support import IDENT, edit
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible, block_path

FAMILY = 'oscillator_phase_hold'
FRESH = 'repair_axis_z'
SAVED = r'\$s[0-7]|\$fp'
FLOAT_REGISTER = r'\$f(?:[0-9]|[12][0-9]|3[01])'
SAVED_FLOAT = r'\$f(?:2[02468]|30)'
LITERAL = r'\d+(?:\.\d+)?[fF]'

_PUBLISH = re.compile(rf'swc1 (?P<z>{SAVED_FLOAT}), %lo\((?P<global>{IDENT})\)\(\$at\)')
_CALL = re.compile(rf'jal ({IDENT})')
_TO_FLOAT = re.compile(rf'mtc1 (?P<gpr>{SAVED}), (?P<scratch>{FLOAT_REGISTER})')
_ACCUMULATE = re.compile(rf'add\.s (?P<scratch>{FLOAT_REGISTER}), (?P=scratch), (?P<axis>{SAVED_FLOAT})')
_TO_WORD = re.compile(rf'mfc1 (?P<gpr>{SAVED}), (?P<scratch>{FLOAT_REGISTER})')
_SHAPE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<global>{IDENT})\s*=\s*(?P<z>[^;\n{{}}]+);[ \t]*\n'
    rf'(?P=pad)\*\s*(?P<dest>{IDENT})\s*=\s*(?P<x>{IDENT});[ \t]*\n'
    rf'(?P=pad){IDENT}\s*\+=\s*{LITERAL};[ \t]*\n'
    rf'(?P=pad)(?P<xacc>{IDENT})\s*\+=\s*(?P=x);[ \t]*\n'
    rf'(?P=pad)(?P<input>{IDENT})\s*=\s*(?P<callee>{IDENT})\((?P<args>[^;\n{{}}]+)\);[ \t]*\n'
    rf'(?P=pad)(?P<old>{IDENT})\s*=\s*\*[^;\n{{}}]+;[ \t]*\n'
    rf'(?P=pad){IDENT}\s*=\s*(?P<product>\(\(\((?P=input)\s*\*\s*(?P<scale>{LITERAL})\)\s*-\s*(?P=old)\))'
)
_WRITE = r'\s*=(?!=)\s*[^;{}]+;'
_ESCAPE = re.compile(r'\b(?:goto|break|continue|return|case|default)\b|(?m:^[ \t]*\w+\s*:)')
_Z_PRODUCT = re.compile(rf'{IDENT}\s*\*\s*\(\s*{IDENT}\([^;{{}}]+\)\s*\*\s*{LITERAL}\s*\)')


def _accumulators(tail):
    for i, (_, line) in enumerate(tail):
        begin = _TO_FLOAT.fullmatch(line)
        if not begin:
            continue
        before = tail[i + 1:i + 8]
        for j, (changed, op) in enumerate(before):
            add = _ACCUMULATE.fullmatch(op)
            if not add or add['scratch'] != begin['scratch']:
                continue
            end = f'mfc1 {begin["gpr"]}, {begin["scratch"]}'
            if any(_TO_WORD.fullmatch(text) and text == end for _, text in before[j + 1:]):
                yield begin['gpr'], add['axis'], changed
            break


def _witnesses(rows):
    target = [(mark != ' ', left) for mark, left, _ in rows if left]
    out = set()
    for i, (changed, line) in enumerate(target):
        store = _PUBLISH.fullmatch(line)
        if not store:
            continue
        call = next(((k, m[1]) for k, (_, op) in enumerate(target[i + 1:i + 6], i + 1)
                     if (m := _CALL.fullmatch(op))), None)
        if not call:
            continue
        at, callee = call
        pairs = list(_accumulators(target[at + 2:at + 22]))
        if (len(pairs) == 2 and pairs[0][0] != pairs[1][0] and pairs[0][1] != store['z']
                and pairs[1][1] == store['z'] and (changed or any(p[2] for p in pairs))):
            out.add((store['global'], callee))
    return out


def _edits(part, m, floats):
    stem = m['x']
    cut = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?P<acc>{IDENT})\s*\+=\s*{m["global"]}\s*;[ \t]*\n')
    after = part.clean[m.end():part.end]
    z = cut.search(part.clean, m.end(), min(m.end() + 6000, part.end))
    if not z or _ESCAPE.search(part.clean[m.end():z.start()]):
        return None
    if (re.search(rf'\b{z["acc"]}\b', part.clean[m.end():z.start()])
            or re.search(rf'\b(?:{m["xacc"]}|{z["acc"]})\b', m['args'])):
        return None
    path = block_path(part, m.start('global'))
    if block_path(part, z.start('acc')) != path:
        return None
    first_x = re.search(rf'\b{stem}\b', after)
    if not first_x:
        return None
    x_at = m.end() + first_x.start()
    next_x = re.match(_WRITE, part.clean[m.end() + first_x.end():])
    preceding = part.clean[m.end():x_at]
    if (not next_x or block_path(part, x_at) != path or _ESCAPE.search(preceding)
            or preceding.rstrip()[-1:] not in (';', '{', '}', ':')
            or re.search(rf'\b{stem}\b', next_x[0])):
        return None
    fields = (stem, m['xacc'], z['acc'], m['input'], m['old'])
    if len(set(fields)) != len(fields) or any(
        key not in floats or not _in_scope(part, floats[key][1], m.start()) or _escaped(part.body, key)
        for key in fields
    ):
        return None
    source = part.source
    pad = m['pad']
    begin = m.start()
    end = m.end()
    if re.search(r'/[*/]|#', source[begin:end]):
        return None
    x_line = source.rfind('\n', begin, m.start('xacc')) + 1
    after_x = source.index('\n', m.end('xacc'), m.start('input')) + 1
    after_call = source.rfind('\n', m.end('input'), m.start('old')) + 1
    insertion = (f'{pad}{m["xacc"]} += {stem};\n{pad}{z["acc"]} += {FRESH};\n'
                 f'{pad}{stem} = {m["input"]} * {m["scale"]};\n')
    return [
        (part.opening + 1, part.opening + 1, f'\n    f32 {FRESH};'),
        (begin, begin, f'{pad}{FRESH} = {m["z"]};\n'),
        (*m.span('z'), FRESH),
        (x_line, after_x, ''),
        (after_call, after_call, insertion),
        (*m.span('product'), f'(({stem} - {m["old"]})'),
        (z.start(), z.end(), ''),
    ]


def variants(source, name, rows, *, header=''):
    """Use the target's saved values instead of reloading an axis after the call."""
    witness = _witnesses(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(rf'\b{FRESH}\b|typedef[^;\n]*\bvolatile\b[^;\n]*\bf32\b', context):
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    options = []
    for m in _SHAPE.finditer(part.clean, part.opening + 1, part.end):
        if (m['global'], m['callee']) not in witness or not _Z_PRODUCT.fullmatch(m['z']):
            continue
        if not re.search(rf'\bextern\s+f32\s+{m["global"]}\s*;', context):
            continue
        edits = _edits(part, m, floats)
        if not edits:
            continue
        identifiers = {key for a, b, text in edits for key in re.findall(IDENT, source[a:b] + text)}
        identifiers.update(re.findall(IDENT, source[m.start():m.end()]))
        macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
        if not macros.intersection(identifiers):
            options.append(edit(source, edits))
    return [(FAMILY, options[0])] if len(options) == 1 else []
