"""m2c's raw display-list stores written back as the SDK's Gbi macros (gDPSetTile, gSPTextureRectangle, ...).

N64 game code builds its display lists with libultra's `gbi.h` macros: `gDPPipeSync(gDisplayListHead++);` expands to
`{ Gfx *_g = (Gfx *)(gDisplayListHead++); _g->words.w0 = 0xE7000000; _g->words.w1 = 0; }`. m2c reads a run of them
back as one read of the cursor global, the words stored through that local at byte offsets in the scheduler's order,
the values computed between them, and then every `cursor = temp + 8 * n` in a row. Nothing in the other families gets
from there to the macros: `display_cursor_record` makes the words record members and moves the advances, but each
macro's own shape (the cursor read once per command, each word an `_SHIFTL` of its own argument, the command written
whole) is what gcc 2.7.2 keyed on. On a 565-instruction N64 text renderer (KMC gcc 2.7.2) writing the m2c draft as
the SDK's macros on a plain `Gfx *` cursor took the judge from 21920 to 3770, the largest single step of its match.

This family finds such runs (a read of a pointer global, the stores through it and through locals derived from it,
its advances, and a later read of the cursor that continues the run in the same block), decodes each command by its
opcode (the high byte of its first word) and the fields of each word (the constants, and the `(x & mask) << shift`
terms m2c printed) against the macros' own encodings in `gbi.h`, and writes the run as one macro per command (three
commands for a texture rectangle) at the place of its last statement, each on `cursor++`. A command it cannot decode
faithfully (a field whose value the macro would mask differently, an opcode it doesn't know) is written as its two
words on the same `Gfx` record (`gRawWords`), so every variant writes exactly the words the draft wrote.

Variants: every run as macros (`gbi_macro_commands`), every run with all commands as raw words (`gbi_raw_commands`,
the cursor and record shape alone) and each run alone as macros (`gbi_macro_run`). The macros are defined in the
source under `#ifndef` (a project whose header includes `gbi.h` keeps its own), as is `Gfx` when nothing defines it.

The RSP commands decoded are F3DEX2's (G_DL 0xDE, G_ENDDL 0xDF, G_TEXTURE 0xD7, G_SETOTHERMODE_H/L 0xE3/0xE2,
G_RDPHALF_1/2 0xE1/0xF1 inside a texture rectangle); the RDP commands (0xE4-0xFF) are the same for every microcode.
Runs that span branches (a command whose words are stored in both arms of an `if`) are not rewritten yet, except one
word stored in both arms of an `if`/`else` through the same pointer: that is one store of the value the branch chose
(`_arm_stores`). m2c also uses the cursor global itself as the base of a run's first words (`M2C_FIELD(gCursor, s32 *,
8) = ...`, `temp_v1 = gCursor + 8;`); those uses are read into a local of the global's type first (`_explicit_reads`),
which is where the run finder starts. When m2c passed a run's locals to a callee as trailing 'arguments' (registers
that still held them at the call), the locals stay in use and no run is private; `gbi_macro_args_trim` drops those
arguments from every call of that callee and from its prototype in the source, and rewrites the runs. On a
638-instruction N64 texture loader (SN gcc 2.8.1) whose draft had all three, the family wrote no child before and
took the draft from 38349 to 30574 after.
"""
import re

from .display_cursor_record_repairs import _records, _statements
from .display_cursor_record_repairs import _store as _record_store
from .integer_repair_support import IDENT, edit, view

FAMILY = 'gbi_macro_commands'
RAW_FAMILY = 'gbi_raw_commands'
RUN_FAMILY = 'gbi_macro_run'
LOCAL_FAMILY = 'gbi_macro_local'
LOCAL_RUN_FAMILY = 'gbi_macro_local_run'
TRIM_FAMILY = 'gbi_macro_args_trim'
FAMILIES = (FAMILY, LOCAL_FAMILY, RAW_FAMILY, RUN_FAMILY, LOCAL_RUN_FAMILY, TRIM_FAMILY)
LIMIT = 10
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'

POINTER = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>void|char|s8|u8|s32|u32|int|unsigned|Gfx)\s*\*\s*(?:volatile\s+)?(?P<name>{IDENT})\s*;')
SIZES = {'s32': 4, 'u32': 4, 'int': 4, 'unsigned': 4, 'Gfx': 8}
M2C_STORE = re.compile(rf'M2C_FIELD\s*\(\s*(?P<p>{IDENT})\s*,\s*(?:s32|u32)\s*\*\s*,\s*(?P<off>{NUMBER})\s*\)\s*=(?!=)\s*(?P<v>[^;]+?)\s*;\Z')
DEREF_STORE = re.compile(rf'\*\s*(?P<p>{IDENT})\s*=(?!=)\s*(?P<v>[^;]+?)\s*;\Z')
DECLARATION = re.compile(rf'(?:{IDENT}\s+)+\**\s*{IDENT}\s*;\Z')
DERIVED = re.compile(rf'(?P<y>{IDENT})\s*=\s*(?P<x>{IDENT})\s*\+\s*(?P<k>{NUMBER})\s*;\Z')
CALL = re.compile(rf'\b(?!(?:if|while|for|switch|return|sizeof|M2C_FIELD)\b)(?!__repair)(?P<f>{IDENT})\s*\(')
CONTROL = re.compile(r'\b(?:goto|return|case|default|break|continue)\b|^\s*\w+\s*:(?!:)', re.M)
CAST = re.compile(r'^\(\s*(?:(?:unsigned|signed)\s+)?(?:s32|u32|int|long|unsigned|s16|u16|short)\s*\)\s*')


RAW_LHS = re.compile(rf'\*(?:s32|u32|int|unsigned|unsignedint)\*(?:char\*)?(?P<p>{IDENT})(?:\+(?P<off>{NUMBER}))?')


def _store(text, records):
    if found := _record_store(text, records):
        return found
    lhs, sep, value = text.partition('=')
    if sep and not value.startswith('=') and not re.search(r'[-+*/|&^<>!]$', lhs.rstrip()):
        flat = re.sub(r'[\s()]', '', lhs)
        if (m := RAW_LHS.fullmatch(flat)) and (m['off'] or flat.count('*') == 1 or 'char' not in flat):
            return m['p'], int(m['off'] or '0', 0), value.rstrip().rstrip(';').strip()
    if m := M2C_STORE.match(text):
        return m['p'], int(m['off'], 0), m['v']
    if m := DEREF_STORE.match(text):
        return m['p'], 0, m['v']
    return None


# ---- expressions ------------------------------------------------------------------------------------------------

def _wrapped(e):
    """True when e's first `(` closes at its very end."""
    if not e.startswith('('):
        return False
    depth = 0
    for i, ch in enumerate(e):
        depth += ch == '('
        depth -= ch == ')'
        if depth == 0:
            return i == len(e) - 1
    return False


def _primary(e):
    """True when e has no top-level binary operator: a cast on it applies to all of it, so dropping the cast drops nothing
    but the conversion (`(s32) (a + 8)` yes, `(s32) (a + 8) >> 3` no: there the cast is the shifted operand's, and
    dropping it turns an arithmetic shift into a logical one on an unsigned operand)."""
    depth = 0
    for i, ch in enumerate(e):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch in '+-*/%&|^<>=?:,' and i > 0 and e[:i].strip() not in ('-', '~', '!', '*', '&'):
            return False
    return True


def _strip(e):
    e = e.strip()
    while True:
        if _wrapped(e):
            e = e[1:-1].strip()
        elif (m := CAST.match(e)) and e[m.end():] and _primary(e[m.end():]):
            e = e[m.end():].strip()
        else:
            return e


def _python_split(e, op):
    """e split on a top-level binary `op` (`|`, `&` or `<<`), never inside parentheses or as `||`/`&&`."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(e):
        ch = e[i]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and e.startswith(op, i):
            before, after = e[i - 1:i], e[i + len(op):i + len(op) + 1]
            if len(op) == 1 and (before == op or after == op or after == '='):
                i += 1
                continue
            parts.append(e[start:i])
            start = i + len(op)
            i = start
            continue
        i += 1
    parts.append(e[start:])
    return [p.strip() for p in parts]


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(e, op):
        found = _scan.split_operator(e, op)
        return _python_split(e, op) if found is NotImplemented else found


def _number(e):
    e = _strip(e)
    m = re.fullmatch(r'(0[xX][0-9a-fA-F]+|\d+)[uUlL]*', e)
    return int(m[1], 0) & 0xFFFFFFFF if m else None


def _mask(value):
    """(shift, width) of a contiguous mask, else None."""
    if value <= 0:
        return None
    shift = (value & -value).bit_length() - 1
    run = value >> shift
    return (shift, run.bit_length()) if run & (run + 1) == 0 else None


def _terms(e):
    """(constant, [(text, shift, width or None)]) of a word: its top-level `|` terms, each a field at a shift."""
    constant, terms = 0, []
    for part in _ors(e):
        if (n := _number(part)) is not None:
            constant |= n
            continue
        part = _strip(part)
        shift, width = 0, None
        pieces = _split(part, '<<')
        if len(pieces) == 2 and (k := _number(pieces[1])) is not None:
            part, shift = _strip(pieces[0]), k
        pieces = _split(part, '&')
        if len(pieces) == 2 and (n := _number(pieces[1])) is not None and (found := _mask(n)):
            low, width = found
            inner = _strip(pieces[0])
            if low and shift:
                return None
            if low:
                part, shift = f'{_paren(inner)} >> {low}', low
            else:
                part = inner
        terms.append((part, shift, width))
    return constant, terms


def _ors(e):
    """The top-level `|` terms of e, parenthesised ORs flattened."""
    out = []
    for part in _split(_strip(e), '|'):
        inner = _strip(part)
        out.extend(_ors(inner) if len(_split(inner, '|')) > 1 else [part])
    return out


def _inline(clean, spans, run, others, body, offset):
    """The run's words with a variable that only carries one of its fields replaced by its value (m2c names the
    `_SHIFTL` of a coordinate computed in a branch: `var_a1_2 = ((x * 4) & 0xFFF) << 12;`), and the statements that
    assigned them, which the rewrite deletes; the variable must be assigned once in the run's block and read nowhere
    but in the run's words (or in other runs' words, or assigned again) and its value's variables not changed after."""
    first, last = run['statements'][0], run['statements'][-1]
    mine = set(run['statements'])
    commands, removed = [], []
    for w0, w1 in run['commands']:
        words = []
        for word in (w0, w1):
            parts = _ors(word)
            for k, part in enumerate(parts):
                name = _strip(part)
                if not re.fullmatch(IDENT, name) or _number(name) is not None:
                    continue
                assign = re.compile(rf'{re.escape(name)}\s*=(?!=)\s*(?P<v>[^;]+);\Z')
                hits = [i for i in range(first, last + 1) if i not in mine and assign.match(clean[spans[i][0]:spans[i][1]])]
                if len(hits) != 1:
                    continue
                i = hits[0]
                value = assign.match(clean[spans[i][0]:spans[i][1]])['v'].strip()
                used = re.compile(rf'(?<![\w.>]){re.escape(name)}\b')
                ok = True
                for j, (a, b) in enumerate(spans):
                    text = clean[a:b]
                    if j == i or j in mine or j in others or not used.search(text) or DECLARATION.match(text):
                        continue
                    if not (assign.match(text) and not used.search(assign.match(text)['v'])):
                        ok = False
                        break
                names = set(re.findall(IDENT, value))
                tail = clean[spans[i][1]:spans[last][1]]
                if not ok or any(re.search(ASSIGNED.format(re.escape(n)), tail) for n in names):
                    continue
                parts[k] = f'({value})'
                removed.append(i)
            words.append(' | '.join(parts) if len(parts) > 1 else parts[0])
        commands.append(tuple(words))
    return commands, removed


def _paren(e):
    return e if re.fullmatch(rf'{IDENT}|{NUMBER}', e) or _wrapped(e) else f'({e})'


# ---- commands ---------------------------------------------------------------------------------------------------

def _fields(word, fields, masked):
    """{argument: text} of a word against [(argument, shift, width)] fields, or None when a macro would not write it.

    Each non-constant term needs a field at its shift that is at least as wide as its own mask (or a top field, whose
    excess bits fall off the word anyway, or a value known to fit); a field takes either a term or its constant."""
    split = _terms(word)
    if split is None:
        return None
    constant, terms = split
    out, covered = {}, 0
    for name, shift, width in fields:
        mask = ((1 << width) - 1) << shift
        covered |= mask
        out[name] = (constant & mask) >> shift
    if constant & ~covered & 0xFFFFFFFF:
        return None
    taken = set()
    for text, shift, width in terms:
        field = next((f for f in fields if f[1] == shift and f[0] not in taken), None)
        if field is None:
            return None
        name, _, size = field
        if out[name]:
            return None
        if width is None:
            if shift + size < 32 and not masked(text, size):
                return None
        elif width > size:
            return None
        elif width < size:
            text = f'{_paren(text)} & {hex((1 << width) - 1)}'
        out[name] = text
        taken.add(name)
    return out


def _arg(value):
    return value if isinstance(value, str) else (hex(value) if value > 9 else str(value))


def _plus(value, k):
    return value + k if not isinstance(value, str) else f'{_paren(value)} + {k}'


COLOR = [('r', 24, 8), ('g', 16, 8), ('b', 8, 8), ('a', 0, 8)]
TILE_W1 = [('tile', 24, 3), ('palette', 20, 4), ('cmt', 18, 2), ('maskt', 14, 4), ('shiftt', 10, 4), ('cms', 8, 2),
           ('masks', 4, 4), ('shifts', 0, 4)]
RECT_W0 = [('uls', 12, 12), ('ult', 0, 12)]
RECT_W1 = [('tile', 24, 3), ('lrs', 12, 12), ('lrt', 0, 12)]
SYNCS = {0xE6: 'gDPLoadSync', 0xE7: 'gDPPipeSync', 0xE8: 'gDPTileSync', 0xE9: 'gDPFullSync'}
COLORS = {0xFB: 'gDPSetEnvColor', 0xF9: 'gDPSetBlendColor', 0xF8: 'gDPSetFogColor'}
IMAGES = {0xFD: 'gDPSetTextureImage', 0xFF: 'gDPSetColorImage'}


def _decode(op, w0, w1, masked):
    """(macro, [argument texts]) for one command's words, or None."""
    n0, n1 = _number(w0), _number(w1)
    if op in SYNCS and n0 == op << 24 and n1 == 0:
        return SYNCS[op], []
    if op == 0xDE and n0 in (0xDE000000, 0xDE010000):
        return ('gSPDisplayList' if n0 == 0xDE000000 else 'gSPBranchList'), [_strip(w1)]
    if op == 0xDF and n0 == 0xDF000000 and n1 == 0:
        return 'gSPEndDisplayList', []
    if op == 0xFE and n0 == 0xFE000000:
        return 'gDPSetDepthImage', [_strip(w1)]
    if op == 0xF7 and n0 == 0xF7000000:
        return 'gDPSetFillColor', [_strip(w1)]
    if op == 0xFC and (a := _fields(w0, [('op', 24, 8), ('muxs0', 0, 24)], masked)):
        return 'gDPSetCombine', [_arg(a['muxs0']), _strip(w1)]
    if op in (0xE2, 0xE3) and n0 is not None:
        length = (n0 & 0xFF) + 1
        shift = 32 - ((n0 >> 8) & 0xFF) - length
        if shift >= 0 and not n0 & 0x00FF0000:
            return 'gSPSetOtherMode', [hex(op), str(shift), str(length), _strip(w1)]
        return None
    if op in IMAGES and (a := _fields(w0, [('op', 24, 8), ('fmt', 21, 3), ('siz', 19, 2), ('width', 0, 12)], masked)) \
            and (b := _fields(w1, [('i', 0, 32)], masked)):
        return IMAGES[op], [_arg(a['fmt']), _arg(a['siz']), _arg(_plus(a['width'], 1)), _arg(b['i'])]
    if op == 0xF5 and (a := _fields(w0, [('op', 24, 8), ('fmt', 21, 3), ('siz', 19, 2), ('line', 9, 9), ('tmem', 0, 9)], masked)) \
            and (b := _fields(w1, TILE_W1, masked)):
        return 'gDPSetTile', [_arg(a[k]) for k in ('fmt', 'siz', 'line', 'tmem')] + [_arg(b[k]) for k, *_ in TILE_W1]
    if op in (0xF2, 0xF4, 0xF3) and (a := _fields(w0, [('op', 24, 8)] + RECT_W0, masked)):
        if op == 0xF3:
            b = _fields(w1, [('tile', 24, 3), ('lrs', 12, 12), ('dxt', 0, 12)], masked)
            # the macro writes MIN(lrs, 2047): only a known lrs can be passed through it unchanged
            if b and isinstance(b['lrs'], int) and b['lrs'] <= 0x7FF:
                return 'gDPLoadBlock', [_arg(b['tile']), _arg(a['uls']), _arg(a['ult']), _arg(b['lrs']), _arg(b['dxt'])]
            return None
        if b := _fields(w1, RECT_W1, masked):
            return ('gDPSetTileSize' if op == 0xF2 else 'gDPLoadTile'), [_arg(b['tile'])] + [_arg(a[k]) for k in ('uls', 'ult')] + \
                [_arg(b[k]) for k in ('lrs', 'lrt')]
        return None
    if op == 0xF0 and n0 == 0xF0000000 and (b := _fields(w1, [('tile', 24, 3), ('count', 14, 10)], masked)):
        return 'gDPLoadTLUTCmd', [_arg(b['tile']), _arg(b['count'])]
    if op == 0xFA and (a := _fields(w0, [('op', 24, 8), ('m', 8, 8), ('l', 0, 8)], masked)) and (b := _fields(w1, COLOR, masked)):
        return 'gDPSetPrimColor', [_arg(a['m']), _arg(a['l'])] + [_arg(b[k]) for k, *_ in COLOR]
    if op in COLORS and n0 == op << 24 and (b := _fields(w1, COLOR, masked)):
        return COLORS[op], [_arg(b[k]) for k, *_ in COLOR]
    if op == 0xD7 and (a := _fields(w0, [('op', 24, 8), ('bowtie', 16, 8), ('level', 11, 3), ('tile', 8, 3), ('on', 1, 7)], masked)) \
            and a['bowtie'] == 0 and (b := _fields(w1, [('s', 16, 16), ('t', 0, 16)], masked)):
        return 'gSPTexture', [_arg(b['s']), _arg(b['t']), _arg(a['level']), _arg(a['tile']), _arg(a['on'])]
    return None


def _rectangle(commands, masked):
    """gSPTextureRectangle(Flip) for an E4/E5 command and the RDPHALF_1/2 pair that follows it, else None."""
    (w0, w1), (h0, h1), (g0, g1) = commands
    op = (_number(w0) or 0) >> 24 if _number(w0) is not None else _opcode(w0)
    if op not in (0xE4, 0xE5) or _number(h0) != 0xE1000000 or _number(g0) != 0xF1000000:
        return None
    a = _fields(w0, [('op', 24, 8), ('xh', 12, 12), ('yh', 0, 12)], masked)
    b = _fields(w1, [('tile', 24, 3), ('xl', 12, 12), ('yl', 0, 12)], masked)
    c = _fields(h1, [('s', 16, 16), ('t', 0, 16)], masked)
    d = _fields(g1, [('dsdx', 16, 16), ('dtdy', 0, 16)], masked)
    if not (a and b and c and d):
        return None
    name = 'gSPTextureRectangle' if op == 0xE4 else 'gSPTextureRectangleFlip'
    return name, [_arg(x) for x in (b['xl'], b['yl'], a['xh'], a['yh'], b['tile'], c['s'], c['t'], d['dsdx'], d['dtdy'])]


def _opcode(w0):
    split = _terms(w0)
    if split is None:
        return None
    constant, terms = split
    if any(shift + (width or 32 - shift) > 24 for _, shift, width in terms):
        return None
    return constant >> 24


DEFINITIONS = {
    '_SHIFTL': '#define _SHIFTL(v, s, w) ((unsigned int)(((unsigned int)(v) & ((0x01 << (w)) - 1)) << (s)))',
    'MIN': '#define MIN(a, b) ((a) < (b) ? (a) : (b))',
    'gRawWords': '#define gRawWords(pkt, a, b) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (a); _g->words.w1 = (b); }',
    'gDPNoParam': '#define gDPNoParam(pkt, cmd) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(cmd, 24, 8); _g->words.w1 = 0; }',
    'gImmp1': '#define gImmp1(pkt, c, p0) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL((c), 24, 8); _g->words.w1 = (unsigned int)(p0); }',
    'gDma1p': '#define gDma1p(pkt, c, s, l, p) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL((c), 24, 8) | _SHIFTL((p), 16, 8) | _SHIFTL((l), 0, 16)); _g->words.w1 = (unsigned int)(s); }',
    'gDPLoadSync': '#define gDPLoadSync(pkt) gDPNoParam(pkt, 0xE6)',
    'gDPPipeSync': '#define gDPPipeSync(pkt) gDPNoParam(pkt, 0xE7)',
    'gDPTileSync': '#define gDPTileSync(pkt) gDPNoParam(pkt, 0xE8)',
    'gDPFullSync': '#define gDPFullSync(pkt) gDPNoParam(pkt, 0xE9)',
    'gSPDisplayList': '#define gSPDisplayList(pkt, dl) gDma1p(pkt, 0xDE, dl, 0, 0)',
    'gSPBranchList': '#define gSPBranchList(pkt, dl) gDma1p(pkt, 0xDE, dl, 0, 1)',
    'gSPEndDisplayList': '#define gSPEndDisplayList(pkt) gDPNoParam(pkt, 0xDF)',
    'gSetImage': '#define gSetImage(pkt, cmd, fmt, siz, width, i) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(cmd, 24, 8) | _SHIFTL(fmt, 21, 3) | _SHIFTL(siz, 19, 2) | _SHIFTL((width) - 1, 0, 12); _g->words.w1 = (unsigned int)(i); }',
    'gDPSetTextureImage': '#define gDPSetTextureImage(pkt, f, s, w, i) gSetImage(pkt, 0xFD, f, s, w, i)',
    'gDPSetColorImage': '#define gDPSetColorImage(pkt, f, s, w, i) gSetImage(pkt, 0xFF, f, s, w, i)',
    'gDPSetDepthImage': '#define gDPSetDepthImage(pkt, i) gSetImage(pkt, 0xFE, 0, 0, 1, i)',
    'gDPSetColor': '#define gDPSetColor(pkt, c, d) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(c, 24, 8); _g->words.w1 = (unsigned int)(d); }',
    'gDPSetFillColor': '#define gDPSetFillColor(pkt, d) gDPSetColor(pkt, 0xF7, d)',
    'gDPSetCombine': '#define gDPSetCombine(pkt, muxs0, muxs1) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(0xFC, 24, 8) | _SHIFTL(muxs0, 0, 24); _g->words.w1 = (unsigned int)(muxs1); }',
    'gSPSetOtherMode': '#define gSPSetOtherMode(pkt, cmd, sft, len, data) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL(cmd, 24, 8) | _SHIFTL(32 - (sft) - (len), 8, 8) | _SHIFTL((len) - 1, 0, 8)); _g->words.w1 = (unsigned int)(data); }',
    'gDPSetTile': '#define gDPSetTile(pkt, fmt, siz, line, tmem, tile, palette, cmt, maskt, shiftt, cms, masks, shifts) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(0xF5, 24, 8) | _SHIFTL(fmt, 21, 3) | _SHIFTL(siz, 19, 2) | _SHIFTL(line, 9, 9) | _SHIFTL(tmem, 0, 9); _g->words.w1 = _SHIFTL(tile, 24, 3) | _SHIFTL(palette, 20, 4) | _SHIFTL(cmt, 18, 2) | _SHIFTL(maskt, 14, 4) | _SHIFTL(shiftt, 10, 4) | _SHIFTL(cms, 8, 2) | _SHIFTL(masks, 4, 4) | _SHIFTL(shifts, 0, 4); }',
    'gDPLoadTileGeneric': '#define gDPLoadTileGeneric(pkt, c, tile, uls, ult, lrs, lrt) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(c, 24, 8) | _SHIFTL(uls, 12, 12) | _SHIFTL(ult, 0, 12); _g->words.w1 = _SHIFTL(tile, 24, 3) | _SHIFTL(lrs, 12, 12) | _SHIFTL(lrt, 0, 12); }',
    'gDPSetTileSize': '#define gDPSetTileSize(pkt, t, uls, ult, lrs, lrt) gDPLoadTileGeneric(pkt, 0xF2, t, uls, ult, lrs, lrt)',
    'gDPLoadTile': '#define gDPLoadTile(pkt, t, uls, ult, lrs, lrt) gDPLoadTileGeneric(pkt, 0xF4, t, uls, ult, lrs, lrt)',
    'gDPLoadBlock': '#define gDPLoadBlock(pkt, tile, uls, ult, lrs, dxt) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL(0xF3, 24, 8) | _SHIFTL(uls, 12, 12) | _SHIFTL(ult, 0, 12)); _g->words.w1 = (_SHIFTL(tile, 24, 3) | _SHIFTL((MIN(lrs, 2047)), 12, 12) | _SHIFTL(dxt, 0, 12)); }',
    'gDPLoadTLUTCmd': '#define gDPLoadTLUTCmd(pkt, tile, count) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = _SHIFTL(0xF0, 24, 8); _g->words.w1 = _SHIFTL((tile), 24, 3) | _SHIFTL((count), 14, 10); }',
    'gDPSetPrimColor': '#define gDPSetPrimColor(pkt, m, l, r, g, b, a) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL(0xFA, 24, 8) | _SHIFTL(m, 8, 8) | _SHIFTL(l, 0, 8)); _g->words.w1 = (_SHIFTL(r, 24, 8) | _SHIFTL(g, 16, 8) | _SHIFTL(b, 8, 8) | _SHIFTL(a, 0, 8)); }',
    'DPRGBColor': '#define DPRGBColor(pkt, cmd, r, g, b, a) gDPSetColor(pkt, cmd, (_SHIFTL(r, 24, 8) | _SHIFTL(g, 16, 8) | _SHIFTL(b, 8, 8) | _SHIFTL(a, 0, 8)))',
    'gDPSetEnvColor': '#define gDPSetEnvColor(pkt, r, g, b, a) DPRGBColor(pkt, 0xFB, r, g, b, a)',
    'gDPSetBlendColor': '#define gDPSetBlendColor(pkt, r, g, b, a) DPRGBColor(pkt, 0xF9, r, g, b, a)',
    'gDPSetFogColor': '#define gDPSetFogColor(pkt, r, g, b, a) DPRGBColor(pkt, 0xF8, r, g, b, a)',
    'gSPTexture': '#define gSPTexture(pkt, s, t, level, tile, on) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL(0xD7, 24, 8) | _SHIFTL(0, 16, 8) | _SHIFTL((level), 11, 3) | _SHIFTL((tile), 8, 3) | _SHIFTL((on), 1, 7)); _g->words.w1 = (_SHIFTL((s), 16, 16) | _SHIFTL((t), 0, 16)); }',
    'gSPTextureRectangle': '#define gSPTextureRectangle(pkt, xl, yl, xh, yh, tile, s, t, dsdx, dtdy) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL(0xE4, 24, 8) | _SHIFTL(xh, 12, 12) | _SHIFTL(yh, 0, 12)); _g->words.w1 = (_SHIFTL(tile, 24, 3) | _SHIFTL(xl, 12, 12) | _SHIFTL(yl, 0, 12)); gImmp1(pkt, 0xE1, (_SHIFTL(s, 16, 16) | _SHIFTL(t, 0, 16))); gImmp1(pkt, 0xF1, (_SHIFTL(dsdx, 16, 16) | _SHIFTL(dtdy, 0, 16))); }',
    'gSPTextureRectangleFlip': '#define gSPTextureRectangleFlip(pkt, xl, yl, xh, yh, tile, s, t, dsdx, dtdy) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (_SHIFTL(0xE5, 24, 8) | _SHIFTL(xh, 12, 12) | _SHIFTL(yh, 0, 12)); _g->words.w1 = (_SHIFTL(tile, 24, 3) | _SHIFTL(xl, 12, 12) | _SHIFTL(yl, 0, 12)); gImmp1(pkt, 0xE1, (_SHIFTL(s, 16, 16) | _SHIFTL(t, 0, 16))); gImmp1(pkt, 0xF1, (_SHIFTL(dsdx, 16, 16) | _SHIFTL(dtdy, 0, 16))); }',
}
NEEDS = {'gDPLoadSync': ['gDPNoParam'], 'gDPPipeSync': ['gDPNoParam'], 'gDPTileSync': ['gDPNoParam'],
         'gDPFullSync': ['gDPNoParam'], 'gSPEndDisplayList': ['gDPNoParam'], 'gSPDisplayList': ['gDma1p'],
         'gSPBranchList': ['gDma1p'], 'gDPSetTextureImage': ['gSetImage'], 'gDPSetColorImage': ['gSetImage'],
         'gDPSetDepthImage': ['gSetImage'], 'gDPSetFillColor': ['gDPSetColor'], 'gDPSetTileSize': ['gDPLoadTileGeneric'],
         'gDPLoadTile': ['gDPLoadTileGeneric'], 'gDPLoadBlock': ['MIN'], 'gDPSetEnvColor': ['DPRGBColor'],
         'gDPSetBlendColor': ['DPRGBColor'], 'gDPSetFogColor': ['DPRGBColor'], 'DPRGBColor': ['gDPSetColor'],
         'gSPTextureRectangle': ['gImmp1'], 'gSPTextureRectangleFlip': ['gImmp1']}
GFX = 'typedef union { struct { unsigned int w0; unsigned int w1; } words; long long force_structure_alignment; } Gfx;'


def _prelude(used, header, source):
    names, seen = ['_SHIFTL'], set()

    def add(name):
        for dependency in NEEDS.get(name, []):
            add(dependency)
        if name not in seen:
            seen.add(name)
            names.append(name)
    for name in used:
        add(name)
    lines = [] if re.search(r'\bGfx\b', header + source) else [GFX]
    for name in dict.fromkeys(names):
        lines.append(f'#ifndef {name}\n{DEFINITIONS[name]}\n#endif')
    return '\n'.join(lines) + '\n'


def _macros(commands, masked, raw=False):
    """[(macro, args)] covering the commands in order; undecodable commands as their raw words."""
    out, i = [], 0
    while i < len(commands):
        w0, w1 = commands[i]
        found = None
        if not raw:
            if i + 2 < len(commands):
                found = _rectangle(commands[i:i + 3], masked)
                if found:
                    out.append(found)
                    i += 3
                    continue
            op = _opcode(w0)
            found = _decode(op, w0, w1, masked) if op is not None else None
        out.append(found or ('gRawWords', [_strip(w0), _strip(w1)]))
        i += 1
    return out


# ---- runs -------------------------------------------------------------------------------------------------------

def _python_depths(clean, start, end):
    depth, out = 0, []
    for i in range(start, end):
        depth += clean[i] == '{'
        depth -= clean[i] == '}'
        out.append(depth)
    return out


_depths = _python_depths
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _depths(clean, start, end):
        found = _scan.brace_depths(clean, start, end)
        return _python_depths(clean, start, end) if found is NotImplemented else found


def _plan(clean, spans, cursor, size, records, start):
    """The runs of `cursor`: reads, derived locals, stores and advances; a later read continues a run when the last
    write to the cursor was that run's advance and no call came between."""
    read = re.compile(rf'(?P<x>{IDENT})\s*=\s*{re.escape(cursor)}\s*;\Z')
    write = re.compile(rf'{re.escape(cursor)}\s*=\s*(?P<p>{IDENT})\s*(?:\+\s*(?P<k>{NUMBER})\s*)?;\Z')
    mention = re.compile(rf'\b{re.escape(cursor)}\b')
    depths = _depths(clean, start, spans[-1][1] if spans else start)
    runs, last, live = [], None, {}  # live: a local's name -> its current version (a read again makes a new one)

    def level(i):
        return depths[spans[i][0] - start]

    def owner(name):
        key = live.get(name)
        return next(((r, key) for r in runs if key in r['base']), (None, None))

    for index, (a, b) in enumerate(spans):
        text = clean[a:b]
        if hit := read.match(text):
            run, old = owner(hit['x'])
            if run is not None:
                run['until'][hit['x']] = a  # what follows is the new read's
            key = live[hit['x']] = f"{hit['x']}#{index}"
            if last is not None and level(last[2]) == level(index) and \
                    min(depths[spans[last[2]][0] - start:a - start]) >= level(index):
                run, origin, _ = last
                run['base'][key] = origin
                run['statements'].append(index)
            else:
                runs.append({'base': {key: ('root',)}, 'statements': [index], 'stores': {}, 'advances': [],
                             'until': {}, 'names': {hit['x']}})
            run = owner(hit['x'])[0]
            run['names'].add(hit['x'])
            continue
        if (d := DERIVED.match(text)) and d['y'] != cursor:
            run, parent = owner(d['x'])
            if run is not None and d['y'] not in live:
                key = live[d['y']] = f"{d['y']}#{index}"
                run['base'][key] = ('from', parent, int(d['k'], 0))
                run['names'].add(d['y'])
                run['statements'].append(index)
            continue
        if (s := _store(text, records)) is not None and owner(s[0])[0] is not None:
            pointer, offset, value = s
            run, key = owner(pointer)
            run['stores'].setdefault((key, offset), []).append((index, value))
            run['statements'].append(index)
            continue
        if w := write.match(text):
            run, key = owner(w['p'])
            if run is None:
                last = None
                continue
            run['advances'].append((index, key, int(w['k'] or '0', 0)))
            run['statements'].append(index)
            last = (run, ('from', key, int(w['k'] or '0', 0)), index)
            continue
        if mention.search(text) or CALL.search(text):
            last = None
    # resolve the bases now that the scale is known: derived and advanced offsets are in the local's units
    out = []
    for run in runs:
        for scale in dict.fromkeys((1, size)):
            resolved = _resolve(run, scale)
            if resolved:
                out.append(resolved)
                break
    return out


def _offset(run, name, scale, depth=0):
    base = run['base'][name]
    if base[0] == 'root' or depth > 32:
        return 0 if base[0] == 'root' else None
    return _offset(run, base[1], scale, depth + 1) + base[2] * scale


def _resolve(run, scale):
    try:
        words = {}
        for (pointer, offset), hits in run['stores'].items():
            if len(hits) != 1 or offset % 4:
                return None
            words[_offset(run, pointer, scale) + offset] = hits[0]
        totals = [_offset(run, p, scale) + k * scale for _, p, k in run['advances']]
    except (KeyError, TypeError):
        return None
    if not words or not totals:
        return None
    count = max(totals) // 8
    if max(totals) % 8 or sorted(words) != list(range(0, count * 8, 4)) or any(t % 8 for t in totals):
        return None
    commands = [(words[8 * k][1], words[8 * k + 4][1]) for k in range(count)]
    return {'statements': sorted(set(run['statements'])), 'commands': commands, 'locals': {n: run['until'].get(n) for n in run['names']},
            'stored': [hit for hits in run['stores'].values() for hit in hits]}


ASSIGNED = r'(?<![\w.>]){0}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.>]){0}\s*(?:\+\+|--)|(?:\+\+|--)\s*{0}\b'


def _movable(clean, spans, run, cursor, body, depths, offset):
    """True when the run can be written at its last statement: one block, no call, label or other use of the cursor
    or of its locals in between, and no value's variable assigned after its store."""
    first, last = run['statements'][0], run['statements'][-1]
    lo, hi = spans[first][0], spans[last][1]
    level = depths[spans[first][0] - offset]
    if any(depths[spans[i][0] - offset] != level for i in run['statements']):
        return False
    if min(depths[lo - offset:hi - offset]) < level:
        return False
    mine = set(run['statements'])
    for index in range(first, last + 1):
        if index in mine:
            continue
        text = clean[spans[index][0]:spans[index][1]]
        if CALL.search(text) or re.search(rf'\b{re.escape(cursor)}\b', text) or CONTROL.search(text):
            return False
        if re.search(r'\*|->|\[', text.split('=')[0]) and '=' in text:
            return False  # a store through a pointer between the words could alias what a value reads
    if CONTROL.search(clean[lo:hi]):
        return False
    for index, value in run['stored']:
        names = set(re.findall(IDENT, value)) - {'M2C_FIELD', 's32', 'u32', 'u16', 's16', 'u8', 's8', 'void', 'char'}
        tail = clean[spans[index][1]:hi]
        if any(re.search(ASSIGNED.format(re.escape(n)), tail) for n in names):
            return False
    return True


def _private(clean, spans, chosen, body, offset):
    """True when the chosen runs' locals are used nowhere but in their own statements (and declarations)."""
    rest = body
    declaration = re.compile(rf'(?:{IDENT}\s+)+\**\s*{IDENT}\s*;\Z')
    mine = [i for run in chosen for i in run['statements']]
    for index in mine + [i for i, (a, b) in enumerate(spans) if declaration.match(clean[a:b])]:
        a, b = spans[index]
        rest = rest[:a - offset] + ' ' * (b - a) + rest[b - offset:]
    return not any(re.search(rf'\b{re.escape(name)}\b', rest[:None if until is None else until - offset])
                   for run in chosen for name, until in run['locals'].items())


LOAD_WIDTH = re.compile(r'^\*\s*\(\s*\(?\s*(?P<t>u8|u16|unsigned\s+char|unsigned\s+short)\s*\*|^M2C_FIELD\s*\(.*,\s*(?P<m>u8|u16)\s*\*\s*,\s*[^,]+\)$'
                        r'|^\(\s*(?P<c>u8|u16|unsigned\s+char|unsigned\s+short)\s*\)')


def _width(e, assigned, seen=()):
    """How many low bits e can have set at most, from its masks, shifts, unsigned narrow loads and the assignments of
    a variable (every one must be known), or None."""
    e = e.strip()
    while _wrapped(e):
        e = e[1:-1].strip()
    parts = _split(e, '&')
    if len(parts) > 1:
        known = [w for w in (_number(p).bit_length() if _number(p) is not None else _width(p, assigned, seen) for p in parts) if w is not None]
        return min(known) if known else None
    parts = _split(e, '<<')
    if len(parts) == 2 and (k := _number(parts[1])) is not None:
        w = _width(parts[0], assigned, seen)
        return None if w is None else w + k
    if (n := _number(e)) is not None:
        return n.bit_length()
    if m := LOAD_WIDTH.match(e):
        kind = m['t'] or m['m'] or m['c']
        return 8 if kind in ('u8', 'unsigned char') or kind.startswith('unsigned c') else 16
    if re.fullmatch(IDENT, e) and e not in seen:
        values = assigned(e)
        widths = [_width(v, assigned, seen + (e,)) for v in values]
        return max(widths) if values and None not in widths else None
    return None


def _masked(clean_body):
    def assigned(name):
        return re.findall(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*([^;]+);', clean_body)

    def check(text, size):
        width = _width(text, assigned)
        return width is not None and width <= size
    return check


def _whole_line(source, start, end):
    """The statement's whole line (with its newline) when nothing else is on it, else the statement."""
    line = source.rfind('\n', 0, start) + 1
    stop = source.find('\n', end)
    stop = len(source) if stop < 0 else stop
    if source[line:start].strip() or source[end:stop].strip():
        return start, end
    return line, min(stop + 1, len(source))


def _python_match_open(clean, close):
    depth = 0
    for i in range(close, -1, -1):
        depth += clean[i] == '}'
        depth -= clean[i] == '{'
        if depth == 0:
            return i
    return -1


_match_open = _python_match_open
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _match_open(clean, close):
        found = _scan.open_every(clean, close, '{', '}', -1)
        return _python_match_open(clean, close) if found is NotImplemented else found


def _distribute(source, name, cursor, records):
    """The words a run stores after an `if`/`else` whose arms both read the cursor into the same local, written at the
    end of each arm instead: m2c hoists the texture rectangle's first word, computed in both arms, past their join.
    Both arms end by falling into the store, so the program is the same; each arm then holds a whole run."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    spans = _statements(clean, part.opening + 1, part.end - 1)
    for index, (a, b) in enumerate(spans):
        found = _store(clean[a:b], records)
        if not found:
            continue
        j = len(clean[:a].rstrip()) - 1
        if clean[j] != '}':
            continue
        else_open = _match_open(clean, j)
        before = clean[:else_open].rstrip()
        if not before.endswith('else'):
            continue
        if_close = len(before[:-4].rstrip()) - 1
        if clean[if_close] != '}':
            continue
        if_open = _match_open(clean, if_close)
        head = clean[:if_open].rstrip()
        if not head.endswith(')') or re.search(r'\belse\s+if\s*\([^{};]*\)\s*$', head):
            continue
        read = re.compile(rf'(?<![\w.>]){re.escape(found[0])}\s*=\s*{re.escape(cursor)}\s*;')
        arms = [(if_open, if_close), (else_open, j)]
        if not all(read.search(clean[o:c]) for o, c in arms):
            continue
        # the stores through that local that follow the join, one after another
        stores, last = [], index
        while last < len(spans):
            c, d = spans[last]
            hit = _store(clean[c:d], records)
            if not hit or hit[0] != found[0] or (stores and clean[spans[last - 1][1]:c].strip()):
                break
            stores.append((c, d))
            last += 1
        text = ' '.join(source[c:d] for c, d in stores)
        line = clean.rfind('\n', 0, if_close) + 1
        indent = re.match(r'[ \t]*', clean[line:])[0]
        edits = [(c, d, '') for c, d in stores]
        edits += [(close, close, f'    {text}\n{indent}' if clean[line:close].strip() == '' else f' {text} ')
                  for _, close in arms]
        return edit(source, edits)
    return source


ARM_PAIR = re.compile(r'\bif\s*\((?P<c>[^{};]*)\)\s*\{(?P<a>[^{};]*;)\s*\}\s*else\s*\{(?P<b>[^{};]*;)\s*\}')


def _arm_stores(source, name, records):
    """`if (c) { STORE = x; } else { STORE = y; }` (one word stored in both arms, through the same pointer at the same
    offset) as one store, `STORE = (c) ? x : y;`: m2c prints a value the program chose by a branch (a texture load's
    `dxt`, divided or not) as the word stored twice, and a run with its word in the arms is no run. The store happens
    once on either path with the same address and value, so the program is the same."""
    part = view(source, name)
    if not part:
        return source
    clean, edits = part.clean, []
    for m in ARM_PAIR.finditer(clean, part.opening, part.end):
        first, second = _store(m['a'].strip(), records), _store(m['b'].strip(), records)
        if not first or not second or first[:2] != second[:2]:
            continue
        a, b = m.start('a'), m.start('b')
        lhs, rhs = source[a:m.end('a')].strip().split('=', 1), source[b:m.end('b')].strip().split('=', 1)
        if lhs[0].strip() != rhs[0].strip():
            continue
        condition = source[m.start('c'):m.end('c')].strip()
        edits.append((m.start(), m.end(), f'{lhs[0].strip()} = ({condition}) ? {lhs[1].strip().rstrip(";").strip()} '
                                           f': {rhs[1].strip().rstrip(";").strip()};'))
    return edit(source, edits) if edits else source


def _explicit_reads(source, name, cursor, kind='void'):
    """Each place m2c used the cursor global itself as a run's base (`M2C_FIELD(gCursor, s32 *, 8) = ...`,
    `temp_v1 = gCursor + 8;`) read into a local first (`_cur1 = gCursor;`), as m2c writes it elsewhere: the run
    finder starts a run at a read of the cursor into a local. A read stays valid until the cursor is written or a
    brace (a branch) or a call comes between; the next use reads it again. The local has the global's own type and the
    global is read at the same place, so the program is the same."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    mention = re.compile(rf'\b{re.escape(cursor)}\b')
    write = re.compile(rf'{re.escape(cursor)}\s*=(?!=)')
    edits, decls, current, previous = [], [], None, None
    for a, b in _statements(clean, start, end):
        text = clean[a:b]
        if previous is not None and re.search(r'[{}]', clean[previous:a]):
            current = None
        previous = b
        if write.match(text):
            if mention.search(text[text.index('=') + 1:]):
                return source  # `cursor = cursor + 8`: m2c's own advance, not this shape
            current = None
            continue
        if CALL.search(text):
            current = None  # the callee may move the cursor: what follows reads it again
            continue
        if not mention.search(text):
            continue
        if re.fullmatch(rf'{IDENT}\s*=\s*{re.escape(cursor)}\s*;', text):
            current = None  # m2c's own read into a local: the run finder starts there already
            continue
        if current is None:
            current = next(n for n in (f'_cur{k}' for k in range(1, 1000)) if n not in clean and n not in decls)
            decls.append(current)
            line = clean.rfind('\n', 0, a) + 1
            edits.append((a, a, f'{current} = {cursor};\n{re.match(r"[ \t]*", clean[line:a])[0]}'))
        edits += [(a + m.start(), a + m.end(), current) for m in mention.finditer(text)]
    if not decls:
        return source
    edits.append((start, start, ''.join(f'\n    {kind} *{d};' for d in decls)))
    return edit(source, edits)


def _trim_arguments(source, name, cursor):
    """Calls that pass a run's local (or anything after it) as a trailing argument, with those arguments dropped from
    every call of that callee in the function and from its prototype in the source. m2c guesses a callee's arguments
    from the registers that still hold a value at the call, so a display-list cursor's derived pointers turn up as a
    one-argument callee's 'arguments'; they keep the run's locals in use and the run is never rewritten. A separate
    child (`gbi_macro_args_trim`): the judge decides whether the callee really takes them."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    spans = _statements(clean, start, end)
    names = {n for run in _plan(clean, spans, cursor, 1, _records(clean[:part.opening]), start) for n in run['locals']}
    if not names:
        return source
    call = re.compile(rf'\b(?P<f>{IDENT})\s*\((?P<args>[^;{{}}]*)\)\s*;')
    keep = {}
    for m in call.finditer(clean, start, end):
        if m['f'] in ('if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD'):
            continue
        args = _split(m['args'], ',')
        cut = next((k for k, x in enumerate(args) if set(re.findall(IDENT, x)) & names), None)
        if cut is not None:
            keep[m['f']] = min(keep.get(m['f'], cut), cut)
    keep = {f: k for f, k in keep.items() if k > 0}
    if not keep:
        return source
    edits = []
    for m in call.finditer(clean, start, end):
        if m['f'] in keep:
            args = _split(source[m.start('args'):m.end('args')], ',')
            edits.append((m.start('args'), m.end('args'), ', '.join(args[:keep[m['f']]])))
    for f, k in keep.items():
        proto = re.compile(rf'(?m)^(?P<head>[^\n;{{}}()]*\b{re.escape(f)}\s*\()(?P<params>[^;(){{}}]*)\)\s*;')
        found = proto.search(clean, 0, part.opening)
        if not found:
            return source  # declared only in a header: a call with fewer arguments would not compile against it
        params = _split(source[found.start('params'):found.end('params')], ',')
        edits.append((found.start('params'), found.end('params'), ', '.join(params[:k])))
    return edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    records = _records(part.clean[:part.opening])
    for pointer in POINTER.finditer(part.clean[:part.opening]):
        source = _distribute(source, name, pointer['name'], records)
        source = _explicit_reads(_arm_stores(source, name, records), name, pointer['name'], pointer['type'])
    result = _variants(source, name, header)
    for pointer in POINTER.finditer(part.clean[:part.opening]):
        trimmed = _trim_arguments(source, name, pointer['name'])
        if trimmed != source:
            result += [(TRIM_FAMILY, text) for family, text in _variants(trimmed, name, header)
                       if family == FAMILY][:max(0, LIMIT - len(result))]
    return result


def _variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    spans = _statements(clean, start, end)
    body = clean[start:end]
    depths = _depths(clean, start, end)
    records = _records(clean[:part.opening])
    masked = _masked(body)
    result = []
    for pointer in POINTER.finditer(clean[:part.opening]):
        cursor = pointer['name']
        runs = [r for r in _plan(clean, spans, cursor, SIZES.get(pointer['type'], 1), records, start)
                if _movable(clean, spans, r, cursor, body, depths, start)]
        if not runs:
            continue
        choices = [(FAMILY, runs, False, False), (LOCAL_FAMILY, runs, False, True), (RAW_FAMILY, runs, True, False)]
        if len(runs) > 1:
            choices += [(RUN_FAMILY, [r], False, False) for r in runs] + [(LOCAL_RUN_FAMILY, [r], False, True) for r in runs]
        local = next(n for n in ('gfx', 'pkt', 'gdl', '_gfx') if not re.search(rf'\b{n}\b', clean))
        for family, chosen, raw, block in choices:
            if not _private(clean, spans, chosen, body, start):
                continue
            edits, used = [], set()
            others = {i for r in runs for i in r['statements']}
            for run in chosen:
                commands, removed = _inline(clean, spans, run, others, body, start)
                for index in removed:
                    edits.append((*_whole_line(source, *spans[index]), ''))
                macros = _macros(commands, masked, raw)
                used.update(m for m, _ in macros)
                last = run['statements'][-1]
                a, b = spans[last]
                line = clean.rfind('\n', 0, a) + 1
                indent = re.match(r'[ \t]*', clean[line:a])[0]
                pkt = local if block else cursor
                lines = [f'{m}({", ".join([pkt + "++"] + args)});' for m, args in macros]
                if block:
                    lines = [f'{{ Gfx *{local} = {cursor};'] + ['    ' + line for line in lines] + [f'    {cursor} = {local}; }}']
                text = f'\n{indent}'.join(lines)
                for index in run['statements']:
                    c, d = spans[index]
                    if index != last:
                        c, d = _whole_line(source, c, d)
                    edits.append((c, d, text if index == last else ''))
            if not edits:
                continue
            declaration = f'{_prelude(sorted(used), header, clean[:part.opening])}extern Gfx *{cursor};'
            if not re.search(r'\bwords\b', header + clean[:part.opening]) and re.search(r'\bGfx\b', header + clean[:part.opening]):
                declaration = declaration.replace('->words.', '->')  # the project's own Gfx names its words w0, w1
            edits.append((pointer.start(), pointer.end(), declaration))
            out = edit(source, edits)
            result.append((family, out))
            if len(result) >= LIMIT:
                return result
    return result
