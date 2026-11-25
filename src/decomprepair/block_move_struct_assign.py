"""m2c's expansion of a GCC block move (word loop, alignment test, `lwl`/`lwr` arm, tail words) as the struct
assignment the game wrote.

GCC copies a record of more than a few words with a loop of four-word moves and a tail; when it cannot prove both
sides word-aligned (a record of bytes, `u8 data[N]`), it tests `(dst | src) & 3` at run time and keeps a second copy
of the loop made of `lwl`/`lwr` and `swl`/`swr`. m2c writes all of it out:

    var_v1 = DST;
    var_a0 = SRC;
    temp_v0 = SRC + 0x210;
    if (((s32) &SRC | (s32) &DST) & 3) {
        do {
            M2C_FIELD(var_v1, s32 *, 0) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 0));
            ... (four words)
            var_a0 += 0x10;
            var_v1 += 0x10;
        } while (var_a0 != temp_v0);
    } else {
        do { ... the same, aligned ... } while (var_a0 != temp_v0);
    }
    M2C_FIELD(var_v1, s32 *, 0) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 0));
    ... (the tail words)

No spelling of those loops gives the compiler's block move back (its pointers, the `j` over the aligned loop and the
tail registers are its own); the one statement `*(Block *)DST = *(Block *)SRC;` with a record of the copied size does.
Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 save-data routine (84 instructions, raw m2c 9473 -> 0): a
0x21C-byte copy between two byte buffers, `typedef struct { u8 data[0x21C]; } Block;`.

block_move_struct_assign
    The run above (the two pointer copies and the end pointer, then one aligned loop or the alignment test with both
    loops in either order, then the tail stores through the two pointers) becomes one assignment. The size is the end
    pointer's offset plus the tail's last byte. Children: a byte record (alignment 1: the run-time test is the
    compiler's) when the draft has the test, a word record (`s32 data[N / 4]`: no test) when it has one aligned loop,
    then the other one (only the byte record when the size is not a multiple of four). Declined when the function
    names one of the three pointers anywhere else (their values after the loop would be lost); their declarations go.

Hypothesis from the match and GCC's `movstrsi_internal` expansion: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'block_move_struct_assign'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_EXPR = r'[^;{}\n]+?'
_HEAD = re.compile(
    rf'(?P<indent>[ \t]*)(?P<d>{_ID})\s*=\s*(?P<dinit>{_EXPR})\s*;[ \t]*\n'
    rf'[ \t]*(?P<s>{_ID})\s*=\s*(?P<sinit>{_EXPR})\s*;[ \t]*\n'
    rf'[ \t]*(?P<e>{_ID})\s*=\s*(?P<ebase>{_EXPR})\s*\+\s*(?P<n>{_NUM})\s*;[ \t]*\n')
_WORD = rf'M2C_FIELD\(\s*(?P<{{0}}>{_ID})\s*,\s*(?P<{{0}}t>[su](?:8|16|32))\s*\*\s*,\s*(?P<{{0}}o>{_NUM})\s*\)'
_STORE = re.compile(
    r'[ \t]*' + _WORD.format('l') + r'\s*=\s*(?:\(\s*[su](?:8|16|32)\s*\)\s*)?'
    r'(?P<un>M2C_UNALIGNED(?:16|32)\(\s*)?' + _WORD.format('r') + r'\s*\)?\s*;[ \t]*\n')
_STEP = re.compile(rf'[ \t]*(?P<v>{_ID})\s*\+=\s*(?P<k>{_NUM})\s*;[ \t]*\n')
_WIDTH = {'8': 1, '16': 2, '32': 4}


def _stores(text, pos, dst, src):
    """The run of copy stores at `pos` from `src` to `dst` at equal offsets: ([(offset, width)], end) ."""
    found = []
    while (m := _STORE.match(text, pos)) is not None:
        if (m['l'], m['r']) != (dst, src) or m['lo'] != m['ro'] or m['lt'][1:] != m['rt'][1:]:
            break
        found.append((int(m['lo'], 0), _WIDTH[m['lt'][1:]]))
        pos = m.end()
    return found, pos


def _loop(text, pos, dst, src, end):
    """One `do { stores; src += k; dst += k; } while (src != end);` at `pos`: (step, end) or None."""
    m = re.compile(r'[ \t]*do\s*\{[ \t]*\n').match(text, pos)
    if not m:
        return None
    words, pos = _stores(text, m.end(), dst, src)
    steps = {}
    while (s := _STEP.match(text, pos)) is not None:
        steps[s['v']] = int(s['k'], 0)
        pos = s.end()
    if not words or set(steps) != {dst, src} or len(set(steps.values())) != 1:
        return None
    step = steps[src]
    if [o for o, _w in words] != list(range(0, step, 4)) or any(w != 4 for _o, w in words):
        return None
    tail = re.compile(rf'[ \t]*\}}\s*while\s*\(\s*{re.escape(src)}\s*!=\s*{re.escape(end)}\s*\)\s*;[ \t]*\n').match(
        text, pos)
    return (step, tail.end()) if tail else None


def _run(text, at):
    """The whole block move starting at the head match `at`: (start, stop, dinit, sinit, size, tested, names)."""
    head = _HEAD.match(text, at)
    if not head:
        return None
    dst, src, end = head['d'], head['s'], head['e']
    if len({dst, src, end}) != 3 or head['ebase'].strip() not in (head['sinit'].strip(), src):
        return None
    pos, tested = head.end(), False
    test = re.compile(r'[ \t]*if\s*\((?P<c>[^{};\n]*)&\s*3\s*\)\s*\)?\s*\{[ \t]*\n').match(text, pos)
    if test:
        first = _loop(text, test.end(), dst, src, end)
        middle = first and re.compile(r'[ \t]*\}\s*else\s*\{[ \t]*\n').match(text, first[1])
        second = middle and _loop(text, middle.end(), dst, src, end)
        closing = second and re.compile(r'[ \t]*\}[ \t]*\n').match(text, second[1])
        if not closing or first[0] != second[0]:
            return None
        pos, tested = closing.end(), True
    else:
        loop = _loop(text, pos, dst, src, end)
        if not loop:
            return None
        pos = loop[1]
    tail, pos = _stores(text, pos, dst, src)
    size = int(head['n'], 0) + max((o + w for o, w in tail), default=0)
    return head.start(), pos, head['indent'], head['dinit'].strip(), head['sinit'].strip(), size, tested, (dst, src, end)


def _drop_locals(text, names, start, stop):
    """Remove the declarations of `names` between `start` and `stop` (nothing else in the function names them)."""
    for name in names:
        decl = re.compile(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?\**[ \t]*\(?\**[ \t]*{re.escape(name)}\b[^;\n]*;[ \t]*\n')
        found = decl.search(text, start, stop)
        if found:
            text = text[:found.start()] + text[found.end():]
            stop -= found.end() - found.start()
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result, seen = [], set()
    pos = opening + 1
    while pos < end:
        line = clean.find('\n', pos, end)
        if line < 0:
            break
        run = _run(clean, line + 1)
        pos = line + 1
        if not run:
            continue
        start, stop, indent, dinit, sinit, size, tested, names = run
        outside = clean[opening:start] + clean[stop:end]
        if any(len(re.findall(rf'\b{re.escape(n)}\b', outside)) > 1 for n in names):
            pos = stop
            continue
        kinds = ['bytes', 'words'] if tested else ['words', 'bytes']
        if size % 4:
            kinds = ['bytes']
        for kind in kinds:
            record = f'__repair_block{size:X}' + ('' if kind == 'bytes' else 'w')
            member = f'u8 data[0x{size:X}]' if kind == 'bytes' else f's32 data[0x{size // 4:X}]'
            typedef = f'typedef struct {{ {member}; }} {record};\n'
            line_text = f'{indent}*({record} *)({dinit}) = *({record} *)({sinit});\n'
            text = source[:start] + line_text + source[stop:]
            body_end = end + len(line_text) - (stop - start)
            text = _drop_locals(text, names, span[0], body_end)
            at = source.rfind('\n', 0, span[0]) + 1
            text = text[:at] + typedef + text[at:]
            if text not in seen:
                seen.add(text)
                result.append((FAMILY, text))
        pos = stop
    return result[:6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
