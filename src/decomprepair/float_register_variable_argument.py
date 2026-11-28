"""A float m2c kept in integer variables on its way to an integer register: the variable, its data and the parameter are `f32`.

A float argument after integer ones travels in an integer register under o32, so the target loads the constant with
`lwc1 $f20, %lo(D)($at)` and moves it over with `mfc1 $a3, $f20` before the `jal`. m2c types the callee from what it saw
elsewhere and writes the whole path as integers:

    extern s32 D_80001000;                       extern f32 D_80001000;
    void g(u8 *, s32, s32, s32, s32);            void g(u8 *, s32, s32, f32, s32);
    s32 temp_fs0;                           ->   f32 temp_fs0;
    temp_fs0 = D_80001000;                       temp_fs0 = D_80001000;
    g(a, 1, 2, temp_fs0, 0);                     g(a, 1, 2, temp_fs0, 0);
    g(b, 1, 2, 0x3F800000, 0);                   g(b, 1, 2, 1.0f, 0);

As integers the value takes a saved integer register and is loaded with `lw`. `float_argument_prototype` handles calls
that pass only literal bits; here at least one passes a variable or a data word. The evidence is the target's own
`mfc1 $aN` before a `jal` of the callee. A variable is retyped only when it is assigned from data words or float bits
and read only as such an argument, and a data word only when every use of it is one of those places, so no other value
changes type. One child with every callee, variable and word together (each alone converts a value instead of moving its
bits). On a 461-instruction N64 menu screen (SN64 GCC 2.8.1, `-mfp32`) the draft without it was the furthest from the
match of any single edit (11035 against 6395 with it and the other edits).
"""
import re

from .csource import _blank, find
from .float_argument_prototype import _calls
from .float_bit_argument_repairs import INTEGER_PARAMETER, TYPE_WORDS, _prototypes, float_text
from .integer_repair_support import split_args
from .target_call_arity_repairs import IDENT, LINE

FAMILY = 'float_register_variable_argument'
FAMILIES = (FAMILY,)
WORD = r'(?:s32|u32|int|M2C_UNK32|M2C_UNK)'
BITS = re.compile(r'(?:0[xX][0-9a-fA-F]+|\d+)')
CAST = re.compile(r'^\(\s*(?:s32|u32|int)\s*\)\s*')
ENDS = {'j', 'jr', 'b', 'beq', 'bne', 'beqz', 'bnez', 'blez', 'bgtz', 'bltz', 'bgez', 'bc1t', 'bc1f', 'beql', 'bnel'}


def moved_floats(asm):
    """{callee: {argument positions an `mfc1 $aN` fills before one of its `jal`s}}."""
    found, filled, pending = {}, set(), None
    for line in asm.splitlines():
        hit = LINE.match(line)
        if not hit:
            filled = set()  # a label: another path joins
            continue
        op, args = hit['op'], hit['args'].strip()
        if op == 'mfc1' and (register := re.match(r'\$a([1-3])\s*,', args)):
            filled.add(int(register[1]))
        if pending:  # this line is the delay slot of the call
            found.setdefault(pending, set()).update(filled)
            filled, pending = set(), None
        elif op == 'jal':
            pending = args
        elif op in ENDS or op == 'jalr':
            filled = set()
    return {callee: positions for callee, positions in found.items() if positions}


def _trim(clean, a, b):
    """The span of the argument without surrounding space or an integer cast."""
    while a < b and clean[a].isspace():
        a += 1
    while b > a and clean[b - 1].isspace():
        b -= 1
    cast = CAST.match(clean[a:b])
    return (a + cast.end() if cast else a), b


def _words(clean, symbol):
    """The type's span in the one `extern <word> symbol;`, or None."""
    hits = list(re.finditer(r'(?m)^[ \t]*extern[ \t]+(' + WORD + r')[ \t]+' + symbol + r'[ \t]*;', clean))
    return hits[0].span(1) if len(hits) == 1 else None


def variants(source, name, asm=''):
    positions = moved_floats(asm or '')
    span = find(source, name)
    if not positions or not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    edits = {}  # (start, end) -> replacement
    arguments = set()  # the spans of every argument that turns into a float
    values = {}  # a local or data word passed at a float position -> its spans there
    for callee, (low, high) in _prototypes(clean, span).items():
        if callee == name or callee not in positions:
            continue
        params = [(low + a, low + b) for a, b in split_args(clean[low:high])]
        calls = _calls(clean, callee, opening, span[1])
        if not calls or any(len(args) != len(params) for args in calls):
            continue
        for index in sorted(positions[callee]):
            if index >= len(params) or not INTEGER_PARAMETER.fullmatch(clean[params[index][0]:params[index][1]]):
                continue
            literals, named = [], []
            for args in calls:
                a, b = _trim(clean, args[index][0], args[index][1])
                text = clean[a:b]
                if BITS.fullmatch(text) and float_text(int(text, 0)):
                    literals.append((a, b, float_text(int(text, 0))))
                elif re.fullmatch(IDENT, text):
                    named.append((text, (a, b), args[index]))
                else:
                    literals = named = None
                    break
            if not named:  # literals only is `float_argument_prototype`'s
                continue
            last = clean[params[index][0]:params[index][1]].split()[-1]
            lead = re.match(r'\s*', clean[params[index][0]:params[index][1]])[0]
            edits[params[index]] = lead + 'f32' + (' ' + last if last not in TYPE_WORDS else '')
            for a, b, text in literals:
                edits[(a, b)] = text
            for value, at, whole in named:
                values.setdefault(value, []).append(at)
                arguments.add(at)
                if clean[whole[0]:at[0]].strip():  # the integer cast would convert the float
                    edits[(whole[0] + len(clean[whole[0]:at[0]]) - len(clean[whole[0]:at[0]].lstrip()), at[0])] = ''
    if not values:
        return []
    body = clean[opening:span[1]]
    symbols = {}  # data words to retype -> the places that may name them
    for value, spans in values.items():
        declared = re.search(r'(?m)^[ \t]*(' + WORD + r')[ \t]+' + value + r'[ \t]*;', body)
        if not declared:
            symbols.setdefault(value, set()).update(spans)
            continue
        allowed = set(spans)
        for store in re.finditer(r'(?<![\w.>])' + value + r'\s*=\s*(' + IDENT + r'|0[xX][0-9a-fA-F]+)\s*;', body):
            allowed.add((opening + store.start(), opening + store.start() + len(value)))
            right = (opening + store.start(1), opening + store.end(1))
            if BITS.fullmatch(store[1]):
                if not float_text(int(store[1], 0)):
                    return []
                edits[right] = float_text(int(store[1], 0))
            else:
                symbols.setdefault(store[1], set()).add(right)
        uses = {(opening + use.start(), opening + use.end())
                for use in re.finditer(r'(?<![\w.>])' + value + r'(?!\w)', body)
                if not declared.start() <= use.start() < declared.end()}
        if uses - allowed:
            return []  # read as an integer somewhere
        edits[(opening + declared.start(1), opening + declared.end(1))] = 'f32'
    for symbol, allowed in symbols.items():
        kind = _words(clean, symbol)
        uses = {(opening + use.start(), opening + use.end())
                for use in re.finditer(r'(?<![\w.>])' + symbol + r'(?!\w)', body)}
        if kind is None or uses - allowed:
            return []
        edits[kind] = 'f32'
    text = source
    for (start, end), replacement in sorted(edits.items(), reverse=True):
        text = text[:start] + replacement + text[end:]
    return [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
