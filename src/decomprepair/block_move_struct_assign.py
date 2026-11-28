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
A small word-aligned record needs no end pointer in the draft: m2c writes the loop's bound in its test,
`do { ... } while (var_v0 != (SRC + 0x90));`, after the two pointer copies (in either order). It is the same block
move, read from that bound (an SN GCC 2.8.1 `-O2` routine that copies two id tables to the stack, 0x90 and 0x78
bytes; its draft types the two cursors `s32 *` and steps them by 0x10, which only the struct assignment gets right).

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
# m2c spells the member at offset 0 as a plain dereference: `*(s32 *)var_v1 = *(s32 *)var_v0;`
_ZERO = re.compile(
    rf'[ \t]*\*\(\s*(?P<lt>[su](?:8|16|32))\s*\*\s*\)\s*(?P<l>{_ID})\s*=\s*(?:\(\s*[su](?:8|16|32)\s*\)\s*)?'
    rf'\*\(\s*(?P<rt>[su](?:8|16|32))\s*\*\s*\)\s*(?P<r>{_ID})\s*;[ \t]*\n')
_STEP = re.compile(rf'[ \t]*(?P<v>{_ID})\s*\+=\s*(?P<k>{_NUM})\s*;[ \t]*\n')
_WIDTH = {'8': 1, '16': 2, '32': 4}


def _stores(text, pos, dst, src):
    """The run of copy stores at `pos` from `src` to `dst` at equal offsets: ([(offset, width)], end) ."""
    found = []
    while (m := _STORE.match(text, pos) or _ZERO.match(text, pos)) is not None:
        plain = m.re is _ZERO
        offset = '0' if plain else m['lo']
        if (m['l'], m['r']) != (dst, src) or (not plain and offset != m['ro']) or m['lt'][1:] != m['rt'][1:]:
            break
        found.append((int(offset, 0), _WIDTH[m['lt'][1:]]))
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


_PAIR = re.compile(
    rf'(?P<indent>[ \t]*)(?P<a>{_ID})\s*=\s*(?P<ainit>{_EXPR})\s*;[ \t]*\n'
    rf'[ \t]*(?P<b>{_ID})\s*=\s*(?P<binit>{_EXPR})\s*;[ \t]*\n')
_TEST = re.compile(r'[ \t]*if\s*\((?P<c>[^{};\n]*)&\s*3\s*\)\s*\)?\s*\{[ \t]*\n')
_DO = re.compile(r'[ \t]*do\s*\{[ \t]*\n')


def _plain(expression):
    return re.sub(r'[\s()&]', '', expression)


def _word_cursors(text, names):
    """Whether every one of `names` is declared a pointer to a four-byte type, so `+= 4` steps sixteen bytes."""
    return all(re.search(rf'\b(?:M2C_UNK|M2C_UNK32|s32|u32|int)\s*\*\s*{re.escape(n)}\s*[;,]', text) for n in names)


def _bounded(text, pos, inits):
    """One `do { stores; steps } while (src != SRC + N);` at `pos`: (dst, src, step, N, end) or None.

    A cursor m2c declared `M2C_UNK *` steps by elements (`var_v0 += 4` after four words) while the bound it writes
    stays in bytes (`&D + 0x510`): the step is then read in bytes."""
    opened = _DO.match(text, pos)
    first = opened and (_STORE.match(text, opened.end()) or _ZERO.match(text, opened.end()))
    if not first:
        return None
    dst, src = first['l'], first['r']
    if dst == src or set(inits) != {dst, src}:
        return None
    words, pos = _stores(text, opened.end(), dst, src)
    steps = {}
    while (step := _STEP.match(text, pos)) is not None:
        steps[step['v']] = int(step['k'], 0)
        pos = step.end()
    if set(steps) != {dst, src} or len(set(steps.values())) != 1:
        return None
    if len(words) == steps[src] and steps[src] > 1 and _word_cursors(text, (dst, src)):
        steps = {name: 4 * value for name, value in steps.items()}
    if [offset for offset, _w in words] != list(range(0, steps[src], 4)) or any(width != 4 for _o, width in words):
        return None
    test = re.compile(
        rf'[ \t]*\}}\s*while\s*\(\s*{re.escape(src)}\s*!=\s*(?P<bound>[^;{{}}\n]+?)\s*\+\s*(?P<n>{_NUM})\s*\)*\s*;'
        r'[ \t]*\n').match(text, pos)
    if not test or _plain(test['bound']) not in (_plain(inits[src]), src) or int(test['n'], 0) % steps[src]:
        return None
    return dst, src, steps[src], int(test['n'], 0), test.end()


def _inline_end(text, at):
    """The block move whose end is written in the loop's test (no end pointer): the same tuple as `_run`.

    A copy of a record that may be unaligned keeps the run-time `& 3` test around two such loops."""
    head = _PAIR.match(text, at)
    if not head:
        return None
    inits = {head['a']: head['ainit'].strip(), head['b']: head['binit'].strip()}
    test = _TEST.match(text, head.end())
    loop = _bounded(text, test.end() if test else head.end(), inits)
    if not loop:
        return None
    dst, src, step, bound, pos = loop
    if test:
        middle = re.compile(r'[ \t]*\}\s*else\s*\{[ \t]*\n').match(text, pos)
        other = middle and _bounded(text, middle.end(), inits)
        closing = other and re.compile(r'[ \t]*\}[ \t]*\n').match(text, other[4])
        if not closing or other[:4] != loop[:4]:
            return None
        pos = closing.end()
    tail, pos = _stores(text, pos, dst, src)
    size = bound + max((o + w for o, w in tail), default=0)
    return head.start(), pos, head['indent'], inits[dst], inits[src], size, bool(test), (dst, src)


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


def _retype_local(text, init, record, start, stop):
    """`&sp10` copied into while `sp10` is one scalar word: declare `sp10` as the copied record, which sizes the frame.

    Left alone (None) when the local is not a scalar declared there; declined (False) when the function reads it by
    value, which a record cannot be."""
    local = re.fullmatch(rf'\(?\s*&\s*({_ID})\s*\)?', init)
    if not local:
        return None
    decl = re.compile(rf'(?m)^([ \t]*)(?:M2C_UNK|M2C_UNK32|s32|u32|int)[ \t]+{local[1]}[ \t]*;')
    found = decl.search(text, start, stop)
    if not found:
        return None
    body = text[found.end():stop]
    if re.search(rf'(?<![&\w.]){local[1]}\b', body):
        return False
    return text[:found.start()] + f'{found[1]}{record} {local[1]};' + text[found.end():]


def _single(source, name):
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
        run = _run(clean, line + 1) or _inline_end(clean, line + 1)
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
            body_end -= len(source[:start] + line_text + source[stop:]) - len(text)
            retyped = _retype_local(text, dinit, record, span[0], body_end)
            if retyped is False:
                continue
            if retyped:
                text = retyped
            at = source.rfind('\n', 0, span[0]) + 1
            if typedef not in source:
                text = text[:at] + typedef + text[at:]
            if text not in seen:
                seen.add(text)
                result.append((FAMILY, text))
        pos = stop
    return result[:6]


def variants(source, name):
    """Each block move written as its assignment, and, with two or more, all of them in one child."""
    return _every_copy(source, name) + _single(source, name)


def _every_copy(source, name):
    """A function with two or more block moves gets them all at once too: each alone leaves the other's cursors
    holding registers (word records first)."""
    texts, text = [], source
    for _ in range(4):
        children = [child for _family, child in _single(text, name)]
        if not children:
            break
        text = children[0]
        texts.append(text)
    return [(FAMILY, texts[-1])] if len(texts) > 1 else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
