"""A display-list cursor the caller passes by address, advanced through the pointer for every command: `(*p)++`.

A game that builds a display list into `Gfx **p` writes each command as `gDPxxx((*p)++, ...)`, so the target loads
`*p`, stores the advanced cursor back and writes the two words, command after command, with a word's value computed
after the first word is stored. m2c reads each as

    temp = *p;                                { Cmd *c = (Cmd *) (*(Cmd **) p)++;
    *p = temp + 8;                              c->w0 = 0xFD100000;
    M2C_FIELD(temp, s32 *, 0) = 0xFD100000;  ->  c->w1 = (s32) table[(u16) (u32) rows[id]]; }
    x = (u16) (u32) rows[id];
    M2C_FIELD(temp, s32 *, 4) = (s32) table[x];

and the locals it names between the two words keep values the compiler held only inside the second one.
`gbi_macro_param_cursor` writes such a run on a local copy of the cursor with one write-back, which is another
program to the compiler; this keeps the write-back per command. Each local set between the cursor's advance and the
second word, and read only there, is written inside the word that reads it.

The draft spells a float converted to unsigned as an `if` against 2147483648.0f, which would stand between the two
words, so those are written as casts first (`unsigned_conversion_repairs`), and with the target's assembly the
symbols m2c declared `char` are also tried at the widths the target loads them (`symbol_width_repairs`).

One function (a 171-instruction N64 palette-texture load, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O1`): refined m2c
draft 3170; the combined child here with the width repair scores 400 (only a signed byte load left, which the
signedness repairs take), and the same rewrite of a repair chain's 220 is exact. Candidates for the exact judge."""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .symbol_width_repairs import variants as widths
from .unsigned_conversion_repairs import variants as conversions

FAMILY = 'param_cursor_each'
FAMILIES = (FAMILY,)
RECORD = 'ParamCommand'
LIMIT = 6
NAME = r'[A-Za-z_]\w*'
HEAD = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<temp>{NAME})\s*=\s*(?:\([^();]*\*\s*\)\s*)?\*\s*(?P<p>{NAME})\s*;[ \t]*\n'
                  rf'[ \t]*\*\s*(?P=p)\s*=\s*(?:\([^();]*\*\s*\)\s*)?\(?\s*(?P=temp)\s*\+\s*8\s*\)?\s*;[ \t]*\n')
ASSIGN = re.compile(rf'(?P<local>{NAME})\s*=(?!=)\s*(?P<value>[^;{{}}]+?)\s*;\Z', re.S)


def _word(temp, offset):
    where = rf'M2C_FIELD\s*\(\s*{temp}\s*,\s*(?:s32|u32)\s*\*\s*,\s*(?:0x)?{offset}\s*\)'
    return re.compile(rf'{where}\s*=(?!=)\s*(?P<value>[^;]+?)\s*;\Z', re.S)


def _statement(clean, at, end):
    """(start, end) of the plain statement at or after `at`, or None at a block, label or the end."""
    while at < end and clean[at].isspace():
        at += 1
    stop = clean.find(';', at, end)
    if stop < 0 or any(c in clean[at:stop] for c in '{}:?'):
        return None
    return at, stop + 1


def _command(source, clean, head, end, counts):
    """One command starting at `head`: (start, end, indent, p, first word, second word) or None."""
    temp, p = head['temp'], head['p']
    first, second = _word(temp, 0), _word(temp, 4)
    values, locals_, at = {}, {}, head.end()
    while 'w1' not in values:
        span = _statement(clean, at, end)
        if not span:
            return None
        text = source[span[0]:span[1]]
        if m := first.match(text):
            if 'w0' in values:
                return None
            values['w0'] = m['value']
        elif m := second.match(text):
            if 'w0' not in values:
                return None
            values['w1'] = m['value']
        else:
            m = ASSIGN.match(text)
            if not m or m['local'] in (temp, p) or m['local'] in locals_ or re.search(rf'\b{temp}\b', m['value']):
                return None
            locals_[m['local']] = m['value']
        at = span[1]
    for local in locals_:
        # its declaration and the uses inside this command: nothing else may name it
        pattern = re.compile(rf'(?<![\w.>]){local}\b')
        inside = len(pattern.findall(clean[head.start():at]))
        if inside < 2 or counts(local) != inside + 1:
            return None
    for local, value in reversed(list(locals_.items())):
        # last set first, so a value naming an earlier local is written out by that local's turn
        pattern = re.compile(rf'(?<![\w.>]){local}\b')
        for key in values:
            values[key] = pattern.sub(lambda _, v=value: f'({v})', values[key])
    if any(re.search(rf'\b{temp}\b', v) for v in values.values()):
        return None
    return head.start(), at, head['indent'], p, values['w0'], values['w1'], temp, list(locals_)


def _rewrite(source, name):
    span = find(source, name)
    if not span or RECORD in source:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    body = clean[opening:end]

    def counts(local):
        return len(re.findall(rf'(?<![\w.>]){local}\b', body))

    parameters = clean[span[0]:opening]
    found, done = [], 0
    for head in HEAD.finditer(clean, opening, end):
        if head.start() < done or not re.search(rf'\bvoid\s*\*\s*\*\s*{head["p"]}\b', parameters):
            continue
        command = _command(source, clean, head, end, counts)
        if command:
            found.append(command)
            done = command[1]
    if len(found) < 2:
        return None
    # a cursor temporary read after its commands keeps the draft's spelling
    spans = [(c[0], c[1]) for c in found]
    for temp in {c[6] for c in found}:
        uses = [opening + m.start() for m in re.finditer(rf'(?<![\w.>]){temp}\b', body)]
        outside = [u for u in uses if not any(a <= u < b for a, b in spans)]
        if len(outside) > 1:
            return None
    gone = {c[6] for c in found} | {local for c in found for local in c[7]}
    edits = [(a, b, f'{indent}{{ {RECORD} *cmd = ({RECORD} *)((*({RECORD} **){p})++); cmd->w0 = {w0}; '
              f'cmd->w1 = {w1}; }}') for a, b, indent, p, w0, w1, _, _ in found]
    for local in gone:
        declared = re.search(rf'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+\**[ \t]*{local}[ \t]*;[ \t]*\n', body)
        rest = [m for m in re.finditer(rf'(?<![\w.>]){local}\b', body)
                if not any(a <= opening + m.start() < b for a, b in spans)]
        if declared and len(rest) == 1:
            edits.append((opening + declared.start(), opening + declared.end(), ''))
    text = source
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    return text[:span[0]] + f'typedef struct {{ unsigned int w0; unsigned int w1; }} {RECORD};\n' + text[span[0]:]


def _casts(source, name, spelling):
    """Every float-to-unsigned `if` written as its cast in one spelling, one at a time."""
    for _ in range(8):
        step = [text for _, text in conversions(source, name) if text.count(spelling) > source.count(spelling)]
        if not step:
            break
        source = step[0]
    return source


def _unsigned_bytes(source, asm):
    """A `char` array the target only loads with `lbu` declared `u8`."""
    def declared(m):
        loads = set(re.findall(rf'\b(lb|lbu)\s+\$\w+\s*,\s*%lo\(\s*{m["symbol"]}\s*\)', asm))
        return f'extern u8 {m["symbol"]}[];' if loads == {'lbu'} else m[0]

    return re.sub(rf'extern\s+char\s+(?P<symbol>{NAME})\s*\[\s*\]\s*;', declared, source)


def variants(source, name, header='', asm=''):
    if not re.search(r'void\s*\*\s*\*', source) or 'M2C_FIELD' not in source:
        return []
    out, seen = [], {source}
    for spelling in ('(u16) (u32)', ' & 0xFFFF'):
        cast = _casts(source, name, spelling)
        seeds = [text for _, text in widths(cast, name, asm)][:LIMIT // 2 - 1] if asm else []
        for seed in seeds + [cast]:
            text = _rewrite(_unsigned_bytes(seed, asm) if asm else seed, name)
            if text and text not in seen:
                seen.add(text)
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm')}
