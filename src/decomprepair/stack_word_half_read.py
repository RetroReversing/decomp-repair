"""A halfword (or byte) read from inside a stack word that was stored whole: the word's own narrowed value.

m2c names the stack slots it saw accessed. A word local the C stores (`sp10 = x * 8;`) that the target later reads
back as a halfword at `0x12($sp)` gets a second, separate local, `unksp12`, that nothing ever assigns, and the draft
copies that uninitialised local (`M2C_FIELD(arg0, u16 *, 0x30) = unksp12;`). Earlier repairs then put a nearby
value in its place (`= temp_s4;`), which is a wrong program. On a big-endian MIPS the halfword at +2 of a word is its
low half: the game wrote `(u16) sp10[0]` and kept the word in memory because it declared the words as one array.

A MIPS GCC 2.7.2 N64 function (`-G0 -mips3 -O1`, 80 instructions) stood at 333 with `sp10[1..3] = ...` stored and
`temp_s4` stored to three halfword fields, and at 0 with `s32 sp10[3]; sp10[0] = a * 8; ... (u16) sp10[0]` (the
word array is what keeps the words on the stack: the same C with three scalar locals scored 638, the compiler holds
them in registers).

This module finds the word slots (`s32`/`u32`/`M2C_UNK` scalars or arrays named `spNN`, assigned somewhere) and the
unassigned `unkspMM` locals that fall inside one, and rewrites each read to the narrowed word:
- `(u16) E` for the halfword at +2 of the word (`(u16) (E >> 16)` at +0), `(u8) (E >> 8*(3-r))` for a byte;
- a word counts as stored when the C assigns it or passes its address (`&spNN`, a bare array name) to a callee;
- the width comes from the local's declared type, else from the pointer type of the store that consumes it;
- children: scalar words merged into one array `s32 spNN[n]` with the cast element read, and the same with the read
  spelt as a halfword view of the array (`((u16 *) spNN)[2 * i + 1]`, the form a game that reads its table through
  a narrower pointer wrote). An already-declared array only gets its reads rewritten.
Big-endian layout only (N64, GameCube/Wii, PS1 is little-endian and is left alone). A candidate for the judge,
never a verdict.
"""
import re

from .csource import _blank, find

FAMILY = 'stack_word_half_read'
FAMILIES = (FAMILY, 'stack_word_half_view')

_WORD = ('s32', 'u32', 'M2C_UNK', 'M2C_UNK32', 'int')
_DECL = re.compile(r'^(?P<indent>[ \t]+)(?P<type>[A-Za-z_]\w*(?:[ \t]+\w+)?)[ \t]+(?P<name>(?:unksp|sp)(?P<off>[0-9A-F]+))'
                   r'(?:\[(?P<count>\d+)\])?;[^\n]*\n', re.M)
_NARROW = {'s16': ('s16', 2), 'u16': ('u16', 2), 'M2C_UNK16': ('s16', 2), 's8': ('s8', 1), 'u8': ('u8', 1),
           'M2C_UNK8': ('s8', 1)}
_TARGET = re.compile(r'\b(u16|s16|u8|s8)\s*\*')


def _width(declared, statement):
    """(type, size) the read has: the declaration's narrow type, else the store that takes it."""
    if declared in _NARROW:
        return _NARROW[declared]
    found = _TARGET.search(statement)
    return (found[1], 2 if found[1][1:] == '16' else 1) if found else None


def _statement(body, at):
    start = max(body.rfind(';', 0, at), body.rfind('{', 0, at), body.rfind('}', 0, at)) + 1
    end = body.find(';', at)
    return body[start:end + 1 if end >= 0 else len(body)]


def _read(expr, kind, size, rem, view=None):
    """The narrowed read of word `expr` at byte `rem` (0..3) in a big-endian word."""
    shift = 8 * (4 - size - rem)
    inner = expr if shift == 0 else f'({expr} >> {shift})'
    return f'({kind}) {inner}'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    body = clean[opening:span[1]]
    decls = list(_DECL.finditer(body))
    words, unks = {}, {}
    for m in decls:
        off = int(m['off'], 16)
        typ = ' '.join(m['type'].split())
        if m['name'].startswith('sp') and typ in _WORD:
            words[off] = (m, int(m['count']) if m['count'] else 0)
        elif m['name'].startswith('unksp') and not m['count']:
            unks[off] = (m, typ)
    reads, done = [], set()
    for off, (m, typ) in unks.items():
        uses = [u for u in re.finditer(r'(?<![\w.>])unksp' + m['off'] + r'\b', body) if not m.start() <= u.start() < m.end()]
        if not uses or any(re.match(r'\s*(?:=(?!=)|[-+*/|&^]=|<<=|>>=|\+\+|--)', body[u.end():]) for u in uses):
            continue
        base = off & ~3
        slot = next(((o, i) for o, (_, c) in words.items() for i in range(c or 1) if o + 4 * i == base), None)
        if slot is None:
            continue
        found = []
        for u in uses:
            wide = _width(typ, _statement(body, u.start()))
            if wide is None or off % wide[1]:
                return []
            found.append((u, slot, wide, off - base))
        reads += found
        done.add(off)
    if not reads:
        return []
    assigned = set()
    for off, (m, count) in words.items():
        name = r'(?<![\w.>])sp' + m['off'] + r'\b'
        # stored by the C, or filled by a callee that receives its address (a bare array name or `&spNN`)
        if re.search(name + r'(?:\[[^\]]*\])?\s*=(?!=)', body) or re.search(r'&\s*' + name, body) \
                or (count and re.search(name + r'(?!\s*\[)', _DECL.sub('', body))):
            assigned.add(off)
    if not assigned:
        return []
    # the run of word scalars around the slots read, stride 4
    used = {r[1][0] for r in reads}
    out = []
    scalars = sorted(o for o, (_, c) in words.items() if not c)
    run = []
    if any(not words[o][1] for o in used):
        lo = min(used)
        hi = max(used)
        while lo - 4 in scalars:
            lo -= 4
        while hi + 4 in scalars:
            hi += 4
        run = [o for o in range(lo, hi + 1, 4) if o in scalars]
        if any(o in run and words[o][1] for o in used):
            return []
    if not (set(run) | used) & assigned:
        return []
    for style, family in (('cast', FAMILY), ('view', 'stack_word_half_view')):
        edits = []
        elem = {}
        if run:
            buf = f'sp{run[0]:X}'
            for i, o in enumerate(run):
                elem[(o, 0)] = (buf, i)
            for o in run:
                m = words[o][0]
                edits.append((opening + m.start(), opening + m.end(),
                              f"{m['indent']}s32 {buf}[{len(run)}];\n" if o == run[0] else ''))
            for o in run:
                for use in re.finditer(r'(?<![\w.>])sp' + words[o][0]['off'] + r'\b(?!\s*\[)', body):
                    if not words[o][0].start() <= use.start() < words[o][0].end():
                        edits.append((opening + use.start(), opening + use.end(), f'{buf}[{elem[(o, 0)][1]}]'))
        for m in (unks[o][0] for o in done):
            edits.append((opening + m.start(), opening + m.end(), ''))
        for u, (o, i), (kind, size), rem in reads:
            m = words[o][0]
            if (o, 0) in elem and not words[o][1]:
                buf, idx = elem[(o, 0)]
                word = f'{buf}[{idx}]'
            elif words[o][1]:
                buf, idx = f'sp{m["off"]}', i
                word = f'{buf}[{i}]'
            else:
                return []
            if style == 'view':
                if size != 2 or rem & 1:
                    edits = None
                    break
                text = f'(({kind} *) {buf})[{2 * idx + rem // 2}]'
            else:
                text = _read(word, kind, size, rem)
            edits.append((opening + u.start(), opening + u.end(), text))
        if edits is None:
            continue
        text = source
        for a, b, rep in sorted(set(edits), reverse=True):
            text = text[:a] + rep + text[b:]
        if text != source and all(text != t for _, t in out):
            out.append((family, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
