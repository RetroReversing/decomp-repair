"""m2c's texture loader on a returned cursor, written as libultra's composite `gDPLoadTextureBlock` macros.

A routine `Gfx *f(Gfx *gfx, ...)` that loads a palette and a texture reads in m2c's draft as chains of cursor locals
(`temp_a = arg0 + 8; temp_b = temp_a + 8;`), raw word stores through them, and the load block's `CALC_DXT` arithmetic
spread over `if`s and temporaries; arms that end in the same commands share a tail through a `goto`. `gbi_macro_commands`
reads a cursor that is a global or passed by address, one command per macro, so it writes nothing here, and the
`gDPLoadBlock` word cannot be decoded as one command anyway: it is the macro's own arithmetic.

This family reads each arm (a `case`, or the block of an `if`) as a whole: the stores at their offsets from the cursor,
with a shared tail copied in place of its `goto`. The command words name the composite macro, and its arguments are
read from the words that carry them as they are (the image address, the tile flags, the tile size's width and height).
The load block word and the arithmetic that built it are the macro's own and are dropped: the judge decides whether the
macro makes them again. An arm with a command it does not know, a gap, a call or a conditional store gives no child.

    gDPSetTextureLUT                    0xE3001001
    gDPLoadTLUT_pal16 / _pal256         0xFD, 0xE8, 0xF5, 0xE6, 0xF0, 0xE7
    gDPLoadTextureBlock / _4b           0xFD, 0xF5, 0xE6, 0xF3, 0xE7, 0xF5, 0xF2

Children: the macros (`gbi_texture_load`; a local that only carried the cursor to the `return` goes), the same with
the narrow locals the image address indexes with widened to `s32` (`gbi_texture_load_wide`: a `u8` palette index is
masked again at its use where the target's is not), and that with m2c's irregular `switch` over the pixel size as an
`if`/`else if` chain and the palette read as a member of a record array (`gbi_texture_load_chain`).

Measured on a 485-instruction N64 texture loader with three pixel sizes (SN GCC 2.8.1 `-mfp64`): one function, whose
byte-identical source was found by writing these macros by hand. From its saved draft: 27385, the wide child 3395."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, view
from .pattern_repairs import close

FAMILY = 'gbi_texture_load'
WIDE_FAMILY = 'gbi_texture_load_wide'
CHAIN_FAMILY = 'gbi_texture_load_chain'
FAMILIES = (FAMILY, WIDE_FAMILY, CHAIN_FAMILY)
_STOP = re.compile(r'[;(\[{]')
_NUM = re.compile(rf'(?:{NUMBER})\Z')
_CAST = re.compile(r'\(\s*(?:s8|u8|s16|u16|s32|u32|int|unsigned int|unsigned|signed int)\s*\)\s*')
_STORE = re.compile(rf'(?:M2C_FIELD\(\s*(?P<base>{IDENT})\s*,[^,]*\*\s*,\s*(?P<off>-?\w+)\s*\)|\*\s*(?P<plain>{IDENT}))'
                    r'\s*=(?!=)\s*(?P<value>.*)\Z', re.S)
_ASSIGN = re.compile(rf'(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>.*)\Z', re.S)
_LABEL = re.compile(rf'\s*(?P<label>case\s+[\w\-]+\s*:|default\s*:|{IDENT}\s*:(?!:))')

MACROS = {
    '_SHIFTL': '#define _SHIFTL(v, s, w) ((unsigned int)(((unsigned int)(v) & ((0x01 << (w)) - 1)) << (s)))',
    'gWords': '#define gWords(pkt, hi, lo) { Gfx *_g = (Gfx *)(pkt); _g->words.w0 = (hi); '
              '_g->words.w1 = (unsigned int)(lo); }',
    'gDPSetTextureLUT': '#define gDPSetTextureLUT(pkt, type) gWords(pkt, 0xE3001001, type)',
    'gDPSetTextureImage': '#define gDPSetTextureImage(pkt, f, s, w, i) gWords(pkt, _SHIFTL(0xFD, 24, 8) | '
                          '_SHIFTL(f, 21, 3) | _SHIFTL(s, 19, 2) | _SHIFTL((w) - 1, 0, 12), i)',
    'gDPSetTile': '#define gDPSetTile(pkt, fmt, siz, line, tmem, tile, palette, cmt, maskt, shiftt, cms, masks, '
                  'shifts) gWords(pkt, _SHIFTL(0xF5, 24, 8) | _SHIFTL(fmt, 21, 3) | _SHIFTL(siz, 19, 2) | '
                  '_SHIFTL(line, 9, 9) | _SHIFTL(tmem, 0, 9), _SHIFTL(tile, 24, 3) | _SHIFTL(palette, 20, 4) | '
                  '_SHIFTL(cmt, 18, 2) | _SHIFTL(maskt, 14, 4) | _SHIFTL(shiftt, 10, 4) | _SHIFTL(cms, 8, 2) | '
                  '_SHIFTL(masks, 4, 4) | _SHIFTL(shifts, 0, 4))',
    'gDPTileSync': '#define gDPTileSync(pkt) gWords(pkt, _SHIFTL(0xE8, 24, 8), 0)',
    'gDPLoadSync': '#define gDPLoadSync(pkt) gWords(pkt, _SHIFTL(0xE6, 24, 8), 0)',
    'gDPPipeSync': '#define gDPPipeSync(pkt) gWords(pkt, _SHIFTL(0xE7, 24, 8), 0)',
    'gDPLoadTLUTCmd': '#define gDPLoadTLUTCmd(pkt, tile, count) gWords(pkt, _SHIFTL(0xF0, 24, 8), '
                      '_SHIFTL(tile, 24, 3) | _SHIFTL(count, 14, 10))',
    'gDPLoadBlock': '#define gDPLoadBlock(pkt, tile, uls, ult, lrs, dxt) gWords(pkt, _SHIFTL(0xF3, 24, 8) | '
                    '_SHIFTL(uls, 12, 12) | _SHIFTL(ult, 0, 12), _SHIFTL(tile, 24, 3) | '
                    '_SHIFTL(((lrs) < 2047 ? (lrs) : 2047), 12, 12) | _SHIFTL(dxt, 0, 12))',
    'gDPSetTileSize': '#define gDPSetTileSize(pkt, t, uls, ult, lrs, lrt) gWords(pkt, _SHIFTL(0xF2, 24, 8) | '
                      '_SHIFTL(uls, 12, 12) | _SHIFTL(ult, 0, 12), _SHIFTL(t, 24, 3) | _SHIFTL(lrs, 12, 12) | '
                      '_SHIFTL(lrt, 0, 12))',
    'gDPLoadTLUT_pal16': '#define gDPLoadTLUT_pal16(pkt, pal, dram) { gDPSetTextureImage(pkt, 0, 2, 1, dram); '
                         'gDPTileSync(pkt); gDPSetTile(pkt, 0, 0, 0, (256 + (((pal) & 0xf) * 16)), 7, 0, 0, 0, 0, 0, '
                         '0, 0); gDPLoadSync(pkt); gDPLoadTLUTCmd(pkt, 7, 15); gDPPipeSync(pkt); }',
    'gDPLoadTLUT_pal256': '#define gDPLoadTLUT_pal256(pkt, dram) { gDPSetTextureImage(pkt, 0, 2, 1, dram); '
                          'gDPTileSync(pkt); gDPSetTile(pkt, 0, 0, 0, 256, 7, 0, 0, 0, 0, 0, 0, 0); gDPLoadSync(pkt); '
                          'gDPLoadTLUTCmd(pkt, 7, 255); gDPPipeSync(pkt); }',
    'G_IM_SIZ_8b': '#define G_IM_SIZ_8b 1\n#define G_IM_SIZ_8b_LOAD_BLOCK 2\n#define G_IM_SIZ_8b_INCR 1\n'
                   '#define G_IM_SIZ_8b_SHIFT 1\n#define G_IM_SIZ_8b_BYTES 1\n#define G_IM_SIZ_8b_LINE_BYTES 1',
    'G_IM_SIZ_16b': '#define G_IM_SIZ_16b 2\n#define G_IM_SIZ_16b_LOAD_BLOCK 2\n#define G_IM_SIZ_16b_INCR 0\n'
                    '#define G_IM_SIZ_16b_SHIFT 0\n#define G_IM_SIZ_16b_BYTES 2\n#define G_IM_SIZ_16b_LINE_BYTES 2',
    'TXL2WORDS': '#define TXL2WORDS(txls, b_txl) (1 > ((txls) * (b_txl) / 8) ? 1 : ((txls) * (b_txl) / 8))\n'
                 '#define CALC_DXT(width, b_txl) (((1 << 11) + TXL2WORDS(width, b_txl) - 1) / TXL2WORDS(width, b_txl))',
    'TXL2WORDS_4b': '#define TXL2WORDS_4b(txls) (1 > ((txls) / 16) ? 1 : ((txls) / 16))\n'
                    '#define CALC_DXT_4b(width) (((1 << 11) + TXL2WORDS_4b(width) - 1) / TXL2WORDS_4b(width))',
    'gDPLoadTextureBlock': '#define gDPLoadTextureBlock(pkt, timg, fmt, siz, width, height, pal, cms, cmt, masks, '
        'maskt, shifts, shiftt) { gDPSetTextureImage(pkt, fmt, siz##_LOAD_BLOCK, 1, timg); gDPSetTile(pkt, fmt, '
        'siz##_LOAD_BLOCK, 0, 0, 7, 0, cmt, maskt, shiftt, cms, masks, shifts); gDPLoadSync(pkt); gDPLoadBlock(pkt, '
        '7, 0, 0, (((width) * (height) + siz##_INCR) >> siz##_SHIFT) - 1, CALC_DXT(width, siz##_BYTES)); '
        'gDPPipeSync(pkt); gDPSetTile(pkt, fmt, siz, (((width) * siz##_LINE_BYTES) + 7) >> 3, 0, 0, pal, cmt, maskt, '
        'shiftt, cms, masks, shifts); gDPSetTileSize(pkt, 0, 0, 0, ((width) - 1) << 2, ((height) - 1) << 2); }',
    'gDPLoadTextureBlock_4b': '#define gDPLoadTextureBlock_4b(pkt, timg, fmt, width, height, pal, cms, cmt, masks, '
        'maskt, shifts, shiftt) { gDPSetTextureImage(pkt, fmt, 2, 1, timg); gDPSetTile(pkt, fmt, 2, 0, 0, 7, 0, cmt, '
        'maskt, shiftt, cms, masks, shifts); gDPLoadSync(pkt); gDPLoadBlock(pkt, 7, 0, 0, (((width) * (height) + 3) '
        '>> 2) - 1, CALC_DXT_4b(width)); gDPPipeSync(pkt); gDPSetTile(pkt, fmt, 0, ((((width) >> 1) + 7) >> 3), 0, 0, '
        'pal, cmt, maskt, shiftt, cms, masks, shifts); gDPSetTileSize(pkt, 0, 0, 0, ((width) - 1) << 2, '
        '((height) - 1) << 2); }',
}
BASE = ('_SHIFTL', 'gWords', 'gDPSetTextureImage', 'gDPSetTile', 'gDPLoadSync', 'gDPPipeSync')
BLOCK = (*BASE, 'gDPLoadBlock', 'gDPSetTileSize')
NEEDS = {
    'gDPSetTextureLUT': ('gWords', 'gDPSetTextureLUT'),
    'gDPLoadTLUT_pal16': (*BASE, 'gDPTileSync', 'gDPLoadTLUTCmd', 'gDPLoadTLUT_pal16'),
    'gDPLoadTLUT_pal256': (*BASE, 'gDPTileSync', 'gDPLoadTLUTCmd', 'gDPLoadTLUT_pal256'),
    'gDPLoadTextureBlock': (*BLOCK, 'TXL2WORDS', 'gDPLoadTextureBlock'),
    'gDPLoadTextureBlock_4b': (*BLOCK, 'TXL2WORDS_4b', 'gDPLoadTextureBlock_4b'),
}
GFX = 'typedef union { struct { unsigned int w0; unsigned int w1; } words; long long force_align; } Gfx;'


class _Unknown(Exception):
    """Something the family cannot read faithfully: no child."""


def _close(text, at):
    """The offset of the bracket that closes the one at `at`."""
    left = text[at]
    after = close(text, at, left, {'(': ')', '{': '}', '[': ']'}[left]) if left in '({[' else None
    if after is None:
        raise _Unknown
    return after - 1


def _statements(clean, start, end):
    """[(start, end)] of the statements in clean[start:end]: labels, `...;`, compound `if`/`switch`/loop statements."""
    out, i = [], start
    while True:
        while i < end and clean[i].isspace():
            i += 1
        if i >= end:
            return out
        label = _LABEL.match(clean, i, end)
        if label:
            out.append((i, label.end()))
            i = label.end()
            continue
        at = i
        head = re.compile(r'(?:if|switch|while|for)\s*\(').match(clean, i, end)
        if head:
            i = _close(clean, head.end() - 1) + 1
            while True:
                while clean[i].isspace():
                    i += 1
                if clean[i] != '{':
                    raise _Unknown
                i = _close(clean, i) + 1
                other = re.compile(r'\s*else\b\s*(?:if\s*\()?').match(clean, i, end)
                if not other:
                    break
                i = other.end()
                if other[0].rstrip().endswith('('):
                    i = _close(clean, i - 1) + 1
        elif clean[i] == '{':
            i = _close(clean, i) + 1
        else:
            while True:
                stop = _STOP.search(clean, i, end)
                if not stop or stop[0] == ';':
                    break
                i = _close(clean, stop.start()) + 1
            i = stop.end() if stop else end
        out.append((at, i))


def _strip(e):
    e = _CAST.sub('', e).strip()
    while e.startswith('(') and _close(e, 0) == len(e) - 1:
        e = e[1:-1].strip()
    return e


def _split(e):
    """The operands of a top-level `|` chain."""
    parts, depth, last = [], 0, 0
    for hit in re.finditer(r'[(\[]|[)\]]|(?<!\|)\|(?!\|)', e):
        if hit[0] == '|':
            if not depth:
                parts.append(e[last:hit.start()])
                last = hit.end()
        else:
            depth += 1 if hit[0] in '([' else -1
    return [*parts, e[last:]]


def _word(e):
    """(constant bits, [other terms]) of an OR chain."""
    e = _strip(e)
    parts = _split(e)
    if len(parts) > 1:
        constant, terms = 0, []
        for part in parts:
            k, more = _word(part)
            constant |= k
            terms += more
        return constant, terms
    if _NUM.match(e):
        return int(e.rstrip('uUlL'), 0) & 0xFFFFFFFF, []
    return 0, [e]


def _substitute(e, values):
    for _ in range(4):
        new = re.sub(rf'(?<![\w.>])({IDENT})\b', lambda m: f'({values[m[1]]})' if m[1] in values else m[1], e)
        if new == e:
            return e
        e = new
    return e


class _Arm:
    """The commands one arm writes: {byte offset from the cursor: the value stored}."""

    def __init__(self, cursor):
        self.at = {cursor: 0}
        self.values = {}
        self.words = {}
        self.results = []

    def read(self, text):
        text = text.rstrip(';').strip()
        if re.match(r'if\s*\(', text):
            if re.search(r'M2C_FIELD\([^;]*\)\s*=(?!=)|(?:^|[;{}])\s*\*\s*\w+\s*=(?!=)', text):
                raise _Unknown
            for name in re.findall(rf'(?<![\w.>])({IDENT})\s*=(?!=)', text):
                if name in self.at:
                    raise _Unknown
                self.values.pop(name, None)
            return
        store = _STORE.match(text)
        if store:
            base = store['base'] or store['plain']
            if base not in self.at:
                raise _Unknown
            offset = self.at[base] + int(store['off'] or '0', 0)
            if offset in self.words:
                raise _Unknown
            self.words[offset] = _strip(_substitute(store['value'], self.values))
            return
        assign = _ASSIGN.match(text)
        if not assign:
            raise _Unknown
        name, value = assign['name'], _strip(assign['value'])
        step = re.fullmatch(rf'({IDENT})(?:\s*\+\s*({NUMBER}))?', value)
        if step and step[1] in self.at:
            self.at[name] = self.at[step[1]] + int(step[2] or '0', 0)
            self.results.append(name)
            return
        if name in self.at or re.search(rf'(?<![\w.>])(?!M2C_FIELD\b){IDENT}\s*\((?!\s*[su](?:8|16|32)\b)', value):
            raise _Unknown
        # A value that reads itself or memory behind a cursor stays a name.
        self.values.pop(name, None)
        value = _substitute(value, self.values)
        if not re.search(rf'\b{name}\b', value):
            self.values[name] = value

    def commands(self):
        count = len(self.words) // 2
        if not count or sorted(self.words) != [4 * i for i in range(2 * count)]:
            raise _Unknown
        return [(self.words[8 * i], self.words[8 * i + 4]) for i in range(count)]


def _opcode(command):
    return _word(command[0])[0] >> 24


def _plain(command, w0, w1=None):
    k0, other0 = _word(command[0])
    k1, other1 = _word(command[1])
    return not other0 and k0 == w0 and (w1 is None or (not other1 and k1 == w1))


def _tile_flags(w1):
    """(tile, palette, cmt, maskt, cms, masks) of a set-tile's second word, the masks as expressions."""
    constant, terms = _word(w1)
    maskt, masks = str((constant >> 14) & 15), str((constant >> 4) & 15)
    for term in terms:
        shift = re.fullmatch(r'(.+?)\s*(<<|\*)\s*(\w+)', term, re.S)
        if not shift or not _NUM.match(shift[3]):
            raise _Unknown
        amount = int(shift[3], 0)
        bits = amount if shift[2] == '<<' else {16: 4}.get(amount)
        if bits == 14:
            maskt = _strip(shift[1])
        elif bits == 4:
            masks = _strip(shift[1])
        else:
            raise _Unknown
    if constant & 0x3C0F:
        raise _Unknown
    return (constant >> 24) & 7, (constant >> 20) & 15, (constant >> 18) & 3, maskt, (constant >> 8) & 3, masks


def _size(w1):
    """(width, height) from a tile size's second word: the two `((side - 1) * 4) & 0xFFF` fields, width first."""
    text = _CAST.sub('', w1)
    sides = []
    for hit in re.finditer(r'-\s*1\s*(\))\s*(?:\*\s*4|<<\s*2)\s*\)?\s*&\s*0xFFF', text):
        depth = 0
        for paren in reversed(list(re.finditer(r'[()]', text[:hit.start(1) + 1]))):
            depth += 1 if paren[0] == ')' else -1
            if not depth:
                sides.append(_strip(text[paren.end():hit.start()]))
                break
    if len(sides) != 2 or not re.search(r'<<\s*(?:0xC|12)\b', text):
        raise _Unknown
    return sides[0], sides[1]


def _decode(commands):
    """[(macro, [arguments])] for every command, or _Unknown."""
    out, i = [], 0
    while i < len(commands):
        ops = [_opcode(c) for c in commands[i:i + 7]]
        first = commands[i]
        k0, other = _word(first[0])
        if ops[0] == 0xE3 and not other and k0 == 0xE3001001:
            out.append(('gDPSetTextureLUT', [first[1]]))
            i += 1
        elif ops[:6] == [0xFD, 0xE8, 0xF5, 0xE6, 0xF0, 0xE7]:
            tile, load, last = commands[i + 2], commands[i + 4], commands[i + 5]
            if not (_plain(first, 0xFD100000) and _plain(commands[i + 1], 0xE8000000, 0)
                    and _plain(tile, 0xF5000100, 0x07000000) and _plain(commands[i + 3], 0xE6000000, 0)
                    and _plain(last, 0xE7000000, 0)):
                raise _Unknown
            if _plain(load, 0xF0000000, 0x0703C000):
                out.append(('gDPLoadTLUT_pal16', ['0', first[1]]))
            elif _plain(load, 0xF0000000, 0x073FC000):
                out.append(('gDPLoadTLUT_pal256', [first[1]]))
            else:
                raise _Unknown
            i += 6
        elif ops == [0xFD, 0xF5, 0xE6, 0xF3, 0xE7, 0xF5, 0xF2]:
            out.append(_block(commands[i:i + 7]))
            i += 7
        else:
            raise _Unknown
    return out


def _block(commands):
    image, load, sync, _, pipe, render, size = commands
    k_image, extra = _word(image[0])
    if extra or k_image & 0x7FFFF or not _plain(sync, 0xE6000000, 0) or not _plain(pipe, 0xE7000000, 0):
        raise _Unknown
    fmt = (k_image >> 21) & 7
    tile, palette, cmt, maskt, cms, masks = _tile_flags(load[1])
    if tile != 7 or palette:
        raise _Unknown
    render_k = _word(render[0])[0]
    siz = (render_k >> 19) & 3
    if (render_k >> 21) & 7 != fmt or siz > 2:
        raise _Unknown
    render_flags = _tile_flags(render[1])
    if render_flags[0] != 0 or render_flags[2:] != (cmt, maskt, cms, masks):
        raise _Unknown
    width, height = _size(size[1])
    tail = [str(render_flags[1]), str(cms), str(cmt), masks, maskt, '0', '0']
    if siz == 0:
        return 'gDPLoadTextureBlock_4b', [image[1], str(fmt), width, height, *tail]
    return 'gDPLoadTextureBlock', [image[1], str(fmt), ('G_IM_SIZ_8b', 'G_IM_SIZ_16b')[siz - 1], width, height, *tail]


def _stores(text):
    return bool(re.search(r'0x(?:FD|F5|F3|F2|E3001001)[0-9A-Fa-f]*\b', text, re.I)) and 'M2C_FIELD(' in text


def _tail(clean, label):
    """The statements after `label:` up to the end of its case."""
    found = re.search(rf'(?m)^[ \t]*{label}\s*:', clean)
    if not found:
        raise _Unknown
    depth = 0
    for brace in re.compile(r'[{}]').finditer(clean, found.end()):
        depth += 1 if brace[0] == '{' else -1
        if depth < 0:
            break
    else:
        raise _Unknown
    out = []
    for a, b in _statements(clean, found.end(), brace.start()):
        out.append((a, b))
        if clean[a:b].startswith(('break', 'return', 'goto', 'case', 'default')):
            return out
    return out


def _arms(part, cursor):
    """[(first, last, ending, commands, results)]: spans of the source to replace, each an arm's run of statements."""
    source, clean = part.source, part.clean
    found = []

    def walk(start, end, aliases=()):
        # Locals an enclosing block set to the cursor still point at the run's first command.
        aliases = list(aliases)
        group = []
        for a, b in _statements(clean, start, end):
            text = clean[a:b]
            inner = text.find('{')
            if _LABEL.fullmatch(text) and text.startswith(('case', 'default')):
                finish(group, 'break', aliases)
                group = []
                continue
            if inner >= 0 and _stores(text):
                finish(group, 'fall', aliases)
                group = []
                opening = a + inner
                walk(opening + 1, _close(clean, opening), aliases)
                after = _close(clean, opening) + 1
                for brace in re.finditer(r'{', clean[after:b]):
                    at = after + brace.start()
                    if clean[after:at].count('{') == clean[after:at].count('}'):
                        walk(at + 1, _close(clean, at), aliases)
                continue
            if text.startswith(('break', 'goto', 'return')):
                finish(group, text, aliases)
                group = []
                continue
            group.append((a, b))
            alias = re.fullmatch(rf'({IDENT})\s*=\s*{cursor}\s*;', text)
            if alias:
                aliases.append(alias[1])
        finish(group, 'fall', aliases)

    def finish(group, ending, aliases):
        if not group or not any(_stores(clean[a:b]) for a, b in group):
            return
        texts = [source[a:b] for a, b in group]
        jump = re.match(rf'goto\s+({IDENT})\s*;', ending)
        if jump:
            tail = _tail(clean, jump[1])
            last = clean[tail[-1][0]:tail[-1][1]]
            if not last.startswith('break'):
                raise _Unknown
            texts += [source[a:b] for a, b in tail if not _LABEL.fullmatch(clean[a:b])][:-1]
        # Statements before the first one that touches the cursor stay as they are.
        begin = next((i for i, (a, b) in enumerate(group)
                      if re.search(rf'\b{cursor}\b', clean[a:b]) and re.search(rf'{cursor}\s*\+|\(\s*{cursor}\s*,', clean[a:b])), None)
        if begin is None:
            raise _Unknown
        arm = _Arm(cursor)
        arm.at.update(dict.fromkeys(aliases, 0))
        for i, text in enumerate(texts):
            text = _blank(text).strip()
            if _LABEL.fullmatch(text):
                continue
            plain = re.fullmatch(rf'({IDENT})\s*=\s*{cursor}\s*;', text)
            if i < begin and not plain:
                continue
            arm.read(text)
        found.append((group[begin][0], group[-1][1], ending, _decode(arm.commands()), arm))

    walk(part.opening + 1, part.end - 1)
    return found


def _rewrite(part, name, header):
    """(the source with every arm as macros, the arms), or None."""
    source, clean = part.source, part.clean
    definition = re.compile(rf'(?m)^(?P<result>(?:void|Gfx)\s*\*)\s*{name}\s*\(\s*(?P<type>(?:void|Gfx)\s*\*)\s*(?P<cursor>{IDENT})\b')
    head = definition.search(clean)
    if not head:
        return None
    cursor = head['cursor']
    arms = _arms(part, cursor)
    if not arms:
        return None
    # Every other use of the cursor must still mean the same once it advances: a plain copy or the return.
    outside = clean[part.opening + 1:part.end - 1]
    for a, b, *_ in sorted(arms, reverse=True, key=lambda arm: arm[0]):
        outside = outside[:a - part.opening - 1] + ' ' * (b - a) + outside[b - part.opening - 1:]
    copies = set()
    for use in re.finditer(rf'[^;{{}}]*\b{cursor}\b[^;{{}}]*;', outside):
        text = re.sub(r'^\s*(?:(?:case\s+\w+|default|\w+)\s*:\s*)*', '', use[0]).strip()
        copy = re.fullmatch(rf'(?:({IDENT})\s*=|return)\s*{cursor}\s*;', text)
        if not copy:
            return None
        if copy[1]:
            copies.add(copy[1])
    # A local the dropped statements set must not be read anywhere else, unless it is written again below.
    read = re.sub(r'(?m)^[ \t]*[\w ]+?[ \t*]+\w+(?:\[\w+\])?[ \t]*;[ \t]*$', '', outside)
    for a, b, _, _, arm in arms:
        end = 8 * (len(arm.words) // 2)
        kept = {n for n in arm.results if arm.at[n] == end and n in copies}
        for local in re.findall(rf'(?<![\w.>])({IDENT})\s*=(?!=)', clean[a:b]):
            if local not in kept and re.search(rf'(?<![\w.>]){local}\b(?!\s*=(?!=))', read):
                return None
    used, text = [], source
    for a, b, ending, commands, arm in sorted(arms, reverse=True, key=lambda arm: arm[0]):
        indent = source[source.rfind('\n', 0, a) + 1:a]
        indent = indent if indent.isspace() else '    '
        lines = []
        for macro, arguments in commands:
            used.append(macro)
            lines.append(f'{macro}({", ".join([f"{cursor}++", *map(str, arguments)])});')
        # A local that held the end of the run (`var_v0 = temp;`) now holds the advanced cursor.
        end = 8 * (len(arm.words) // 2)
        for result in dict.fromkeys(arm.results):
            if arm.at[result] == end and result in copies:
                lines.append(f'{result} = {cursor};')
        if ending != 'fall':
            lines.append('return ' + cursor + ';' if ending.startswith('return') else 'break;')
        stop = b
        closing = re.compile(r'\s*(?:break|goto\s+\w+|return[^;]*)\s*;').match(clean, b)
        if ending != 'fall' and closing:
            stop = closing.end()
        text = text[:a] + ('\n' + indent).join(lines) + text[stop:]
    new_clean = _blank(text)
    if re.search(rf'\b{cursor}\s*\+(?!\+)', new_clean[new_clean.index('{', head.start()):]):
        return None
    for result in sorted(copies):
        text = _returned(text, head.start(), result, cursor)
    start = head.start()
    text = text[:start] + f'Gfx *{name}(Gfx *{cursor}' + text[head.end():]
    needed = dict.fromkeys(macro for command in used for macro in NEEDS[command])
    if 'gDPLoadTextureBlock' in used:
        needed.update(dict.fromkeys(('G_IM_SIZ_8b', 'G_IM_SIZ_16b')))
    lines = [] if re.search(r'}\s*Gfx\s*;', header + source) else [GFX]
    for macro in needed:
        lines.append(f'#ifndef {macro}\n{MACROS[macro]}\n#endif')
    # The definitions and any prototype go in front of the function.
    return text[:start] + '\n'.join(lines) + '\n' + text[start:], arms


def _returned(text, start, result, cursor):
    """`result = cursor; ... return result;` as `return cursor;` when the local does nothing else."""
    clean = _blank(text)
    body = clean.index('{', start)
    uses = [m.start() + body for m in re.finditer(rf'(?<![\w.>]){result}\b', clean[body:])]
    drop, returns = [], []
    for at in uses:
        line = clean.rfind('\n', 0, at) + 1
        end = clean.find('\n', at)
        row = clean[line:end].strip()
        if re.fullmatch(rf'{result}\s*=\s*{cursor}\s*;', row):
            drop.append((line, end + 1, ''))
        elif re.fullmatch(rf'return\s+{result}\s*;', row):
            returns.append((at, at + len(result), cursor))
        elif not re.fullmatch(rf'[\w ]+?[\s*]+{result}\s*;', row):
            return text
        else:
            drop.append((line, end + 1, ''))
    if not returns:
        return text
    for a, b, new in sorted(drop + returns, reverse=True):
        text = text[:a] + new + text[b:]
    return text


def _if_chain(text):
    """m2c's irregular switch (`case A: .. break; case B: .. break; default: if (v == C) {..} break;`) as the
    `if`/`else if` chain it came from, which compares in the written order and not as a switch's binary tree."""
    for head in re.finditer(rf'switch\s*\(\s*(?P<value>{IDENT})\s*\)\s*{{', _blank(text)):
        clean = _blank(text)
        opening = head.end() - 1
        closing = _close(clean, opening)
        body = text[opening + 1:closing]
        if not re.search(r'\bgDPLoadTextureBlock', body):
            continue
        plain = _blank(body)
        labels = list(re.finditer(r'(?m)^[ \t]*(?:case\s+(?P<case>\w+)|default)\s*:', plain))
        if len(labels) < 2 or labels[-1]['case'] or any(not label['case'] for label in labels[:-1]):
            continue
        arms = []
        for label, nxt in zip(labels, [*labels[1:], None]):
            part = body[label.end():nxt.start() if nxt else len(body)]
            last = re.search(r'\bbreak\s*;\s*\Z', _blank(part))
            if not last:
                break
            arms.append((label['case'], part[:last.start()]))
        if len(arms) != len(labels):
            continue
        value = head['value']
        guard = re.match(rf'\s*if\s*\(\s*{value}\s*==\s*(\w+)\s*\)\s*{{', _blank(arms[-1][1]))
        if not guard:
            continue
        rest = arms[-1][1]
        end = _close(_blank(rest), guard.end() - 1)
        if rest[end + 1:].strip():
            continue
        third = re.sub(r'\bbreak\s*;\s*\Z', '', rest[guard.end():end].rstrip())
        arms[-1] = (guard[1], third)
        if any(re.search(r'\b(?:break|continue|goto)\b', _blank(part)) for _, part in arms):
            continue
        chain = ' else '.join(f'if ({value} == {case}) {{{part.rstrip()}\n        }}' for case, part in arms)
        return text[:head.start()] + chain + text[closing + 1:]
    return None


def _records(text):
    """An image address read through byte arithmetic on a table, `*((i * 8) + table + 4)`, as a member of a record
    array: the constant offset then stays in the load instead of being folded into the table's address."""
    read = re.compile(rf'M2C_FIELD\(\(\((?P<index>{IDENT}) \* (?P<size>\w+)\) \+ (?P<table>{IDENT})\), '
                      r'(?P<type>s32|u32) \*, (?P<offset>\w+)\)')

    def member(hit):
        size, offset = int(hit['size'], 0), int(hit['offset'], 0)
        if offset <= 0 or offset + 4 > size:
            return hit[0]
        after = f' char pad1[{size - offset - 4}];' if size > offset + 4 else ''
        return (f'((struct {{ char pad0[{offset}]; {hit["type"]} data;{after} }} *) {hit["table"]})'
                f'[{hit["index"]}].data')
    return '\n'.join(read.sub(member, line) if re.match(r'\s*gDPLoad', line) else line for line in text.split('\n'))


def _widened(text, arms):
    """The narrow locals an image address indexes with, as s32."""
    names = {n for arm in arms for macro, args in arm[3] if macro != 'gDPSetTextureLUT'
             for n in re.findall(IDENT, args[0] if macro != 'gDPLoadTLUT_pal16' else args[1])}
    new = text
    for name in sorted(names):
        new = re.sub(rf'(?m)^([ \t]*)(?:u8|u16)([ \t]+{name}[ \t]*;)', r'\1s32\2', new)
    return new if new != text else None


def variants(source, name, header=''):
    if 'M2C_FIELD(' not in source or not re.search(r'0xFD[0-9A-F]{6}', source, re.I):
        return []
    part = view(source, name)
    if not part:
        return []
    try:
        rewritten = _rewrite(part, name, header)
    except (_Unknown, IndexError, ValueError):
        return []
    if not rewritten:
        return []
    text, arms = rewritten
    wide = _widened(text, arms)
    out = ([(WIDE_FAMILY, wide)] if wide else []) + [(FAMILY, text)]
    try:
        chain = _records(_if_chain(wide or text) or wide or text)
    except (_Unknown, IndexError, ValueError):
        return out
    return ([(CHAIN_FAMILY, chain)] if chain != (wide or text) else []) + out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',),
          'order': 60}
