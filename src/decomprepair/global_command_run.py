"""m2c's batched writes through a global display-list cursor, written as one block-scoped packet per command.

Several `gSP...(gfx++)` macros in a row compile to one load of the cursor, the cursor advanced and stored once per
command, then the words of every command. m2c names each advanced value and writes the words wherever they landed:

    temp_v1 = gfx + 8;                         { __repair_cmd *_g = (*(__repair_cmd **) &gfx)++;
    M2C_FIELD(gfx, s32 *, 4) = B;                _g->w0 = A; _g->w1 = (u32) (B); }
    temp_t0 = temp_v1 + 8;                 ->  { __repair_cmd *_g = (*(__repair_cmd **) &gfx)++;
    M2C_FIELD(gfx, s32 *, 0) = A;                _g->w0 = C; _g->w1 = (u32) (D); }
    M2C_FIELD(temp_v1, s32 *, 4) = D;
    gfx = temp_v1;
    gfx = temp_t0;
    M2C_FIELD(temp_v1, s32 *, 0) = C;

Each run of such statements is evaluated symbolically from the cursor's value on entry. It is rewritten only when the
cursor ends a whole number of 8-byte commands further on, every word of those commands is stored exactly once, the
temporaries are not used outside the run and no stored value reads the cursor or a temporary. m2c also prints a write
through the entry value's register by the cursor's name after it stored the advanced cursor (`gfx = temp_v1 + 0x18;
M2C_FIELD(gfx, s32 *, 8) = C;` for the second command): when C's reading does not tile the commands, that one is tried.
The macro's post-increment matters: GCC keeps the old value as a copy (`addu $v0,$v1,$zero; addiu $v1,$v1,8`), which
`p = gfx; gfx = p + 8` does not give. A single command (`t = gfx; gfx += 8; ...`) is the same rewrite. One child with
every run: they share the cursor's declaration. On a 461-instruction N64 menu screen (SN64 GCC 2.8.1) leaving these
runs as m2c wrote them scored 8330 against 6395.
`asm_cursor_commands` reads the commands from the target instead; on that function it found none of the batched run
(only the single pipe sync), so this reads the draft.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_command_run'
FAMILIES = (FAMILY,)
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LINE = re.compile(r'(?m)^[ \t]*([^\n{}]*;)[ \t]*\n')
ADVANCE = re.compile(rf'({IDENT})\s*=\s*({IDENT})(?:\s*\+\s*({NUMBER}))?\s*;')
STEP = re.compile(rf'({IDENT})\s*\+=\s*({NUMBER})\s*;')
WRITE = re.compile(rf'M2C_FIELD\(\s*({IDENT})\s*,\s*(?:s32|u32|M2C_UNK|M2C_UNK32|void|u8)\s*\*+\s*,\s*({NUMBER})\s*\)'
                   r'\s*=\s*(.+?)\s*;')


def _runs(source, clean, low, high, cursor):
    """[(start, end, indent, statements)] of consecutive lines that only move or write through `cursor`."""
    runs, current, temps, last = [], [], {cursor}, None
    for line in LINE.finditer(clean, low, high):
        text = line[1]
        kind = None
        if (hit := ADVANCE.fullmatch(text)) and hit[2] in temps and (hit[1] == cursor or hit[1].startswith('temp_')):
            kind = ('copy', hit[1], hit[2], int(hit[3] or '0', 0))
        elif (hit := STEP.fullmatch(text)) and hit[1] == cursor:
            kind = ('copy', cursor, cursor, int(hit[2], 0))
        elif (hit := WRITE.fullmatch(text)) and hit[1] in temps:
            at = line.start(1) + hit.start(3)
            kind = ('write', hit[1], int(hit[2], 0), source[at:at + len(hit[3])])
        if current and (kind is None or line.start() != last):
            runs.append(current)
            current, temps = [], {cursor}
        if kind is None:
            continue
        if kind[0] == 'copy':
            temps.add(kind[1])
        current.append((line, kind))
        last = line.end()
    if current:
        runs.append(current)
    return runs


def _commands(run, cursor, entry):
    """[(w0, w1)] in address order, with the temporaries named, or None. With `entry`, a write based on the cursor's name
    means its value on entry (m2c prints the entry value's register by that name after the cursor was stored)."""
    values, words, temps = {cursor: 0}, {}, set()
    for _, kind in run:
        if kind[0] == 'copy':
            to, of, step = kind[1], kind[2], kind[3]
            if of not in values:
                return None
            values[to] = values[of] + step
            if to != cursor:
                temps.add(to)
        else:
            base, offset, value = kind[1], kind[2], kind[3]
            if base not in values:
                return None
            at = offset if entry and base == cursor else values[base] + offset
            if at in words:
                return None
            words[at] = value
    total = values[cursor]
    if total <= 0 or total % 8 or sorted(words) != list(range(0, total, 4)):
        return None
    named = temps | {cursor}
    if any(named & set(re.findall(IDENT, value)) for value in words.values()):
        return None
    return [(words[at], words[at + 4]) for at in range(0, total, 8)], temps


def variants(source, name):
    part = view(source, name)
    if not part or 'M2C_FIELD(' not in source:
        return []
    clean, low, high = part.clean, part.opening, part.end
    outside = clean[:low] + clean[high:]
    edits, used = [], set()
    for declared in re.finditer(rf'(?m)^[ \t]*extern[ \t]+void[ \t]*\*[ \t]*({IDENT})[ \t]*;', _blank(source)):
        cursor = declared[1]
        for run in _runs(source, clean, low, high, cursor):
            found = _commands(run, cursor, False) or _commands(run, cursor, True)
            if not found:
                continue
            commands, temps = found
            start, end = run[0][0].start(), run[-1][0].end()
            rest = clean[low:start] + clean[end:high] + outside
            uses = [temp for temp in temps
                    if len(re.findall(rf'(?<![\w.>]){temp}(?!\w)', rest)) > len(re.findall(
                        rf'(?m)^[ \t]*[\w ]+\*?[ \t]*\*?{temp}[ \t]*;', rest))]
            if uses:
                continue
            first = run[0][0]
            indent = source[first.start():first.start(1)]
            text = ''.join(f'{indent}{{ __repair_cmd *_g = (*(__repair_cmd **) &{cursor})++; '
                           f'_g->w0 = {w0}; _g->w1 = (u32) ({w1}); }}\n' for w0, w1 in commands)
            edits.append((start, end, text))
            used |= temps
    if not edits:
        return []
    child = edit(source, edits)
    after = view(child, name)
    for temp in used:
        declaration = re.search(rf'(?m)^[ \t]*void[ \t]*\*[ \t]*{temp}[ \t]*;[ \t]*\n', after.clean[after.opening:after.end])
        if declaration and len(re.findall(rf'(?<![\w.>]){temp}(?!\w)', after.clean[after.opening:after.end])) == 1:
            start = after.opening + declaration.start()
            child = child[:start] + child[after.opening + declaration.end():]
            after = view(child, name)
    if 'typedef struct { u32 w0; u32 w1; } __repair_cmd;' not in child:
        at = child.rfind('\n', 0, child.index(re.search(r'(?m)^[ \t]*extern[ \t]+void[ \t]*\*', child)[0])) + 1
        child = child[:at] + 'typedef struct { u32 w0; u32 w1; } __repair_cmd;\n' + child[at:]
    return [(FAMILY, child)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
