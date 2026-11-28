"""The SDK's 16.16 fixed-point matrix read back as floats, and the two words each pair converts held in locals.

`guMtxL2F` (libultra) walks two word streams (integer halves, then fraction halves), packs two 16.16 values from each
pair of words and converts them into `mf[row][pair * 2]` and `mf[row][pair * 2 + 1]`. m2c writes it with its own
cursors, byte steps on word pointers, a goto loop and each conversion inline. On an SN GCC 2.8.1 N64 build the match
needs the two packed words computed before the first conversion (the target shifts the integer word in place before
`mtc1`), the matrix indexed by row and pair (the row pointer is the loop pass's own), and the scale written as a
literal (`lui $at; lwc1` of the pool). A 38-instruction function: the saved draft 890 -> 0, with the literal form that
converted inline at 240.

Two families:

- `packed_fixed_matrix_to_float`: when the whole target has this routine's instructions and the draft is a
  `void f(T *, U *)` that masks with the packing masks, the loop is written out as above. The signature is kept.
- `conversion_operand_pair`: two adjacent statements that each convert a bracketed integer expression with an
  explicit integer cast (`(f32) (s32) (EXPR)`) get both expressions in locals set before the first statement, so the
  second value is computed before the first conversion. Only plain locals and parameters whose address is never taken
  may appear in the expressions (no memory reads, no calls), so the move cannot change what either statement reads.

This module reads text only and never compiles or judges. The candidate is never a verdict: the judge decides."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view
from .measured_stack_drafts import _lines
from .pattern_repairs import close

MATRIX_FAMILY = 'packed_fixed_matrix_to_float'
PAIR_FAMILY = 'conversion_operand_pair'
FAMILIES = (MATRIX_FAMILY, PAIR_FAMILY)
_ONE_65536TH = 0x37800000
_MASK = r'(?:\(0xFFFF0000 >> 16\)|0xFFFF)'
_ZERO = r'(?:0x0|0)?'
_FREG = r'\$f\w+'
_LABEL = r'\.L\w+'
_TARGET = re.compile(
    rf'move \$t0, \$a1\naddiu \$t1, \$t0, (?:0x20|32)\nmove \$t3, \$zero\nlui \$t4, {_MASK}\n'
    rf'(?:lui \$at, %hi\((?P<symbol>{IDENT})\)\nlwc1 (?P<scale>{_FREG}), %lo\((?P=symbol)\)\(\$at\)\n'
    rf'|lui \$at, (?:\(0x37800000 >> 16\)|0x3780)\nmtc1 \$at, (?P<inline>{_FREG})\n)'
    rf'move \$t2, \$a0\n(?P<outer>{_LABEL}):\nmove \$a3, \$zero\nmove \$a2, \$t2\n(?P<inner>{_LABEL}):\n'
    rf'lw \$v1, {_ZERO}\(\$t0\)\nlw \$a1, {_ZERO}\(\$t1\)\naddiu \$t1, \$t1, (?:0x4|4)\n'
    r'and \$a0, \$v1, \$t4\nsrl \$v0, \$a1, (?:0x10|16)\nor \$a0, \$a0, \$v0\nsll \$v1, \$v1, (?:0x10|16)\n'
    rf'mtc1 \$a0, (?P<first>{_FREG})\ncvt\.s\.w (?P=first), (?P=first)\n'
    rf'mul\.s (?P=first), (?P=first), {_FREG}\n'
    r'and \$v1, \$v1, \$t4\nandi \$a1, \$a1, 0xFFFF\nor \$v1, \$v1, \$a1\n'
    rf'mtc1 \$v1, (?P<second>{_FREG})\ncvt\.s\.w (?P=second), (?P=second)\n'
    rf'mul\.s (?P=second), (?P=second), {_FREG}\n'
    r'addiu \$t0, \$t0, (?:0x4|4)\naddiu \$a3, \$a3, (?:0x1|1)\nslti \$v0, \$a3, (?:0x2|2)\n'
    rf'swc1 (?P=first), {_ZERO}\(\$a2\)\nswc1 (?P=second), (?:0x4|4)\(\$a2\)\nbnez \$v0, (?P=inner)\n'
    r'addiu \$a2, \$a2, (?:0x8|8)\naddiu \$t3, \$t3, (?:0x1|1)\nslti \$v0, \$t3, (?:0x4|4)\n'
    r'bnez \$v0, (?P=outer)\naddiu \$t2, \$t2, (?:0x10|16)\njr \$ra\nnop',
    re.I,
)
_CONVERTED = re.compile(r'\(\s*(?:f32|float)\s*\)\s*\(\s*(?P<kind>s32|u32|int)\s*\)\s*(?=\()')
_STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<text>[^\n;{}=]+=(?!=)[^\n;{}]+;)[ \t]*$')
_CAST = re.compile(r'\(\s*(?:s8|u8|s16|u16|s32|u32|int|unsigned(?:\s+int)?)\s*\)')
_PURE = re.compile(rf'(?:\s|{IDENT}|0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|<<|>>|[&|^+\-~()])*')


def target_scale(asm):
    """None when `asm` is not this routine; else the pool symbol its scale is read from ('' when built inline)."""
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm or '')
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    found = _TARGET.fullmatch(lines)
    return None if not found else found['symbol'] or ''


def recover(source, name, asm, words=None):
    """The loop written out from the target, under the draft's own signature; None when either does not fit."""
    symbol = target_scale(asm)
    if symbol is None or (symbol and words and words.get(symbol, _ONE_65536TH) != _ONE_65536TH):
        return None
    part = view(source, name)
    if not part or '__repair_fixed_' in source:
        return None
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\s*\(\s*(?:[\w ]+?[ *]+)(?P<matrix>{IDENT})(?:\s*\[\d*\])*\s*,'
        rf'\s*(?:[\w ]+?[ *]+)(?P<fixed>{IDENT})\s*\)\s*$', part.clean[:part.opening])
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = part.clean[start:end]
    if not signature or not re.search(r'0xFFFF0000\b', body, re.I) or not re.search(r'0xFFFF\b', body, re.I):
        return None
    matrix, fixed = signature['matrix'], signature['fixed']
    written = f'''
    float (*__repair_fixed_rows)[4] = (float (*)[4]) {matrix};
    int __repair_fixed_row, __repair_fixed_pair;
    unsigned int *__repair_fixed_integer, *__repair_fixed_fraction;
    unsigned int __repair_fixed_whole, __repair_fixed_part;
    unsigned int __repair_fixed_first, __repair_fixed_second;

    __repair_fixed_integer = (unsigned int *) {fixed};
    __repair_fixed_fraction = __repair_fixed_integer + 8;

    for (__repair_fixed_row = 0; __repair_fixed_row < 4; __repair_fixed_row++) {{
        for (__repair_fixed_pair = 0; __repair_fixed_pair < 2; __repair_fixed_pair++) {{
            __repair_fixed_whole = *__repair_fixed_integer;
            __repair_fixed_part = *__repair_fixed_fraction++;
            __repair_fixed_first = (__repair_fixed_whole & 0xFFFF0000) | (__repair_fixed_part >> 16);
            __repair_fixed_second = ((__repair_fixed_whole << 16) & 0xFFFF0000) | (__repair_fixed_part & 0xFFFF);
            __repair_fixed_rows[__repair_fixed_row][__repair_fixed_pair * 2] = (float) (int) __repair_fixed_first * (1.0f / 65536.0f);
            __repair_fixed_rows[__repair_fixed_row][__repair_fixed_pair * 2 + 1] = (float) (int) __repair_fixed_second * (1.0f / 65536.0f);
            __repair_fixed_integer++;
        }}
    }}
'''
    return edit(source, [(start, end, written)])


def _plain_names(expression, body, clean):
    """Is `expression` bit and sum arithmetic on integer locals or parameters whose address is never taken?"""
    text = _CAST.sub(' ', expression)
    # Only names, integer constants and bit or sum operators: no `*`, `[`, `.`, `->`, calls or assignments, and every
    # `&` after an operand (a unary one would take an address).
    if not _PURE.fullmatch(text) or re.search(r'\+\+|--|(?:^|[(|^+\-~<>&])\s*&(?![&])', text.strip()):
        return False
    names = set(re.findall(r'(?<![\w.])[A-Za-z_]\w*', text))
    for item in names:
        declared = re.search(rf'(?<![\w.>])(?:s8|u8|s16|u16|s32|u32|int|unsigned|signed|char|short|long)'
                             rf'(?:\s+(?:int|char|short|long))?\s+(?:{IDENT}\s*,\s*)*{item}\s*(?=[;,)=\[])', clean)
        if not declared or re.search(rf'(?:[=(,{{;?:]|return)\s*&\s*{item}\b', body):
            return False
    return bool(names)


def pairs(source, name):
    """One child per pair of adjacent statements that each convert a bracketed integer expression."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0])
    if opening < 0 or opening >= span[1]:
        return []
    body = clean[opening:span[1]]
    found = []
    statements = list(_STATEMENT.finditer(clean, opening, span[1]))
    for first, second in zip(statements, statements[1:]):
        if clean[first.end():second.start()].strip():
            continue
        sites = []
        for hit in (first, second):
            conversions = list(_CONVERTED.finditer(clean, hit.start(), hit.end()))
            if len(conversions) != 1:
                break
            begin = conversions[0].end()
            stop = close(clean, begin)
            if stop > hit.end() or not _plain_names(source[begin:stop], body, clean):
                break
            sites.append((begin, stop, conversions[0]['kind']))
        if len(sites) != 2:
            continue
        # The first statement must not write a name the second expression reads.
        written = re.match(rf'\s*({IDENT})\s*(?:[-+*/|&^]|<<|>>)?=', first['text'])
        if written and re.search(rf'(?<![\w.]){written[1]}\b', source[sites[1][0]:sites[1][1]]):
            continue
        names = []
        for _ in sites:
            local = f'staged_word{len(names)}'
            while re.search(rf'\b{local}\b', source):
                local += '_'
            names.append(local)
        indent = first['indent']
        lines = ''.join(f'{indent}{local} = {source[a + 1:b - 1]};\n' for local, (a, b, _) in zip(names, sites))
        declarations = ''.join(f'\n    {kind} {local};' for local, (_, _, kind) in zip(names, sites))
        edits = [(opening + 1, opening + 1, declarations), (first.start(), first.start(), lines)]
        edits += [(a, b, local) for local, (a, b, _) in zip(names, sites)]
        found.append(edit(source, edits))
    return found


def variants(source, name, asm='', words=None):
    out = []
    matrix = recover(source, name, asm, words) if asm else None
    if matrix:
        out.append((MATRIX_FAMILY, matrix))
    out.extend((PAIR_FAMILY, child) for child in pairs(source, name)[:4])
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'words'), 'order': 66,
          'archs': ('mips',)}
