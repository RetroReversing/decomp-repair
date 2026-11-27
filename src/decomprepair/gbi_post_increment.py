"""m2c's one-command-at-a-time display-list writes through a pointer parameter, written as libultra's `gfx++` macros.

A function that takes `Gfx **gfxp` and passes `(*gfxp)++` to every Gbi macro reads, in m2c's draft, as one run per
command: `t = *arg0; *arg0 = t + 8; M2C_FIELD(t, s32 *, 0) = w0; M2C_FIELD(t, M2C_UNK **, 4) = w1;`. The SDK's macro is
`{ Gfx *_g = (Gfx *)(pkt); _g->words.w0 = w0; _g->words.w1 = w1; }`, and the draft's spelling gives the allocator other
registers and orders the stores differently. `gbi_macro_param_cursor` covers a cursor read once and stored back at the
end; it finds nothing here, since the cursor is stored after every command. Each command is its own block, so branches
and loops are no obstacle (N64 KMC GCC 2.7.2 `-O1` functions of 170 to 530 instructions matched by hand this way).

Children (`gbi_post_increment`):
- the third: the second after each arithmetic temporary that only feeds command words is written into all of them;
- every command as a block where its second word was stored (statements between stay ahead of it);
- the same with each temporary that only feeds one of the command's words written into that word and the block where
  the cursor was read, as a macro's arguments are evaluated.

The words keep m2c's own expressions, so the program stores the same values at the same addresses.
"""
import re

from .csource import _blank, find

FAMILY = 'gbi_post_increment'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
GFX = 'typedef union { struct { unsigned int w0; unsigned int w1; } words; long long force_structure_alignment; } Gfx;\n'
PARAMETER = re.compile(rf'(?:void|s32|u32|int|Gfx)\s*\*\s*\*\s*(?P<name>{IDENT})\s*(?=[,)])')
ASSIGN = re.compile(rf'(?P<v>{IDENT}) = (?P<e>.+);')


def _word(line, temp, offset):
    found = re.fullmatch(rf'M2C_FIELD\({temp}, [\w ]+\*+, {offset}\) = (?P<e>.+);', line)
    return found and found['e']


def _pure(text, temp, cursor):
    """A statement a command's block may move across: a plain local assignment that touches neither the cursor nor
    its copy, and calls nothing."""
    found = ASSIGN.fullmatch(text)
    if not found or re.search(rf'\b(?:{temp}|{cursor})\b', text):
        return False
    return not re.search(rf'\b(?!sizeof|M2C_FIELD){IDENT}\s*\(', found['e'])


def _commands(lines, cursor):
    """(read line, advance line, w0 line, w1 line, copy, w0, w1) for each whole command in `lines` (stripped)."""
    out = []
    for i in range(len(lines) - 3):
        read = re.fullmatch(rf'(?P<t>{IDENT}) = \*{cursor};', lines[i])
        if not read or lines[i + 1] != f'*{cursor} = {read["t"]} + 8;':
            continue
        temp, words, at = read['t'], {}, {}
        for j in range(i + 2, len(lines)):
            for offset in (0, 4):
                value = _word(lines[j], temp, offset)
                if value is not None and offset not in words:
                    words[offset], at[offset] = value, j
                    break
            else:
                if not _pure(lines[j], temp, cursor):
                    break
            if len(words) == 2:
                break
        if len(words) == 2 and at[0] < at[4]:
            out.append((i, i + 1, at[0], at[4], temp, words[0], words[4]))
    return out


def _shared(lines):
    """`lines` with each plain arithmetic temporary that only feeds command words written into them: m2c names a value
    two commands use (a texture's last column), where the macros' arguments compute it in place. Only a local assigned
    once, from locals and constants (no memory read, no call), whose operands are not assigned before its last use."""
    lines, at = list(lines), 0
    while at < len(lines):
        found = ASSIGN.fullmatch(lines[at].strip())
        at += 1
        if not found or not re.fullmatch(r'[\w\s()+\-<>&|^]*', found['e']):
            continue
        name, value = found['v'], found['e']
        word = re.compile(rf'\b{name}\b')
        uses = [k for k, line in enumerate(lines) if k != at - 1 and word.search(line)
                and not re.fullmatch(rf'[\w ]+\*? ?{name};', line.strip())]
        if not uses or uses[0] < at or not all(re.match(r'\s*M2C_FIELD\([^=]*\) = ', lines[k]) for k in uses):
            continue
        operands = '|'.join(set(re.findall(rf'\b{IDENT}\b', value)) - {'s32', 'u32', 's16', 'u16', 's8', 'u8'})
        changed = operands and re.compile(rf'\b(?:{operands})\b\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\b(?:{operands})\b\s*(?:\+\+|--)')
        if changed and any(changed.search(line) for line in lines[at:uses[-1]]):
            continue
        for k in uses:
            lines[k] = word.sub(lambda m, v=value: f'({v})', lines[k])
        del lines[at - 1]
        at -= 1
    return lines


def _block(indent, cursor, w0, w1):
    return (f'{indent}{{ Gfx *_g = (Gfx *)((*(Gfx **){cursor})++); _g->words.w0 = ({w0}); '
            f'_g->words.w1 = (unsigned int)({w1}); }}')


def _rewrite(lines, commands, cursor, clean, inline):
    dropped, placed = set(), {}
    for read, advance, first, second, _, w0, w1 in commands:
        taken, where = [], second
        if inline:
            between = [k for k in range(advance + 1, second) if k != first]
            for k in reversed(between):
                found = ASSIGN.fullmatch(lines[k].strip())
                name = found['v']
                uses = len(re.findall(rf'\b{name}\b', w0 + '|' + w1))
                # used by these two words and nowhere else (its declaration and assignment are the other two)
                if not uses or len(re.findall(rf'\b{name}\b', clean)) != uses + 2:
                    break
                value = f'({found["e"]})'
                w0 = re.sub(rf'\b{name}\b', lambda m, v=value: v, w0)
                w1 = re.sub(rf'\b{name}\b', lambda m, v=value: v, w1)
                taken.append(k)
            if len(taken) == len(between):
                where = read
        indent = re.match(r'[ \t]*', lines[read])[0]
        dropped.update([read, advance, first, second, *taken])
        placed[where] = _block(indent, cursor, w0, w1)
    return [placed.get(k, line) for k, line in enumerate(lines) if k in placed or k not in dropped]


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    head = clean[clean.rfind('\n', 0, clean.rfind(name, 0, opening)) + 1:opening]
    body = source[opening:span[1]]
    result, seen = [], set()
    for parameter in PARAMETER.finditer(head):
        cursor = parameter['name']
        for inline, shared in ((False, False), (True, False), (True, True)):
            lines = body.split('\n')
            if shared:
                lines = _shared(lines)
            commands = _commands([line.strip() for line in lines], cursor)
            if not commands:
                break
            text = '\n'.join(_rewrite(lines, commands, cursor, '\n'.join(lines), inline))
            if text in seen:
                continue
            seen.add(text)
            typedef = '' if re.search(r'\}\s*Gfx\s*;', header + source[:opening]) else GFX
            start = source.rfind('\n', 0, source.rfind(name, 0, opening)) + 1
            result.append((FAMILY, source[:start] + typedef + source[start:opening] + text + source[span[1]:]))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
