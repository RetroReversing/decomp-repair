"""Byte counters and byte parameters m2c wrote as masked words.

gcc 2.7.2 keeps a `u8` loop counter in a word register and masks it (`andi $v0, $s1, 0xFF`) wherever it is read.
m2c writes that back as a word counter and a masked copy:

    var_s1 = 0;
    if (temp_a1 < (u8) M2C_FIELD(arg0, u8 *, 0x19)) {
        var_v0 = 0 & 0xFF;
        do {
            ... var_v0 ...
            var_s1 += 1;
            var_v0 = var_s1 & 0xFF;
        } while ((u32) (var_s1 & 0xFF) < (u8) M2C_FIELD(arg0, u8 *, 0x19));
    }

which is `u8 var_s1; for (var_s1 = 0; var_s1 < LIMIT; var_s1++) { ... var_s1 ... }`. The entry test is m2c's copy of
the compiler's: its left side must be 0, or a variable an immediately preceding `if (x != 0) { ... return; }` has
just shown to be 0. Labels `masked_counter_loop`.

m2c also types a parameter it sees stored with `sb` as `s8` and then masks it (`temp = arg1 & 0xFF`); the source had
`u8`. When every use is such a mask or a store to a byte, `u8` gives the same values (`byte_parameter_sign`).

An N64 game's function needed both: either alone left 32 or 41 instructions different, both together 2.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILIES = ('masked_counter_loop', 'byte_parameter_sign')
MASKS = {'0xFF': 'u8', '0xff': 'u8', '255': 'u8', '0xFFFF': 'u16', '0xffff': 'u16', '65535': 'u16'}
MASK = r'(?:0[xX][fF]{2}(?:[fF]{2})?|255|65535)'


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (span, clean, opening, end) if end else None


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return re.sub(r'^\((?:u8|u16|s32|u32|unsigned char|unsigned short)\)\s*', '', text).strip()


def byte_parameters(source, name):
    """`s8 p` used only as `p & 0xFF` or stored to a byte, as `u8 p` (and `s16`/0xFFFF as `u16`)."""
    found = _body(source, name)
    if not found:
        return []
    span, clean, opening, end = found
    signature = clean.rfind('(', span[0], opening)
    result = []
    for hit in re.finditer(r'\b(s8|s16|signed char|short)\s+(' + IDENT + r')\s*(?=[,)])', clean[signature:opening]):
        param, narrow = hit[2], 'u8' if hit[1] in ('s8', 'signed char') else 'u16'
        mask = r'0[xX][fF]{2}|255' if narrow == 'u8' else r'0[xX][fF]{4}|65535'
        width = r'[su]8|(?:un)?signed char|char' if narrow == 'u8' else r'[su]16|(?:unsigned )?short'
        body = clean[opening:end]
        uses = [m.start() for m in re.finditer(r'(?<![\w.>])' + param + r'\b', body)]
        # (a whole operand only: `(p & 0xFF)`, or `p & 0xFF` between `=`/`(`/`,`/`return` and `;`/`)`/`,`, never
        # `x + p & 0xFF`, which is `(x + p) & 0xFF`)
        masked = list(re.finditer(r'(?<![\w\])])\(\s*' + param + r'\s*&\s*(?:' + mask + r')\s*\)|(?:(?<=[=(,])|(?<=return))\s*'
                                  + param + r'\s*&\s*(?:' + mask + r')\s*(?=[;),])', body))
        stored = list(re.finditer(r'(?:M2C_FIELD\([^;]*?,\s*(?:' + width + r')\s*\*\s*,[^;]*?\)|\*\s*\(\s*(?:' + width
                                  + r')\s*\*\s*\)[^;=]*?)\s*=\s*' + param + r'\s*;', body))
        if not uses or len(uses) != len(masked) + len(stored) or not masked:
            continue
        edits = [(signature + hit.start(1), signature + hit.end(1), narrow)]
        edits += [(opening + m.start(), opening + m.end(), (' ' if m[0][:1].isspace() else '') + param) for m in masked]
        result.append(('byte_parameter_sign', _apply(source, edits)))
    return result


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def counter_loops(source, name):
    found = _body(source, name)
    if not found:
        return []
    span, clean, opening, end = found
    result = []
    for do in re.finditer(r'\bdo\s*{', clean[opening:end]):
        start = opening + do.end() - 1
        stop = close(clean, start, '{', '}')
        tail = re.match(r'\s*while\s*\((.*?)\)\s*;', clean[stop:end], re.S) if stop else None
        if not tail:
            continue
        cond = re.fullmatch(r'\s*(?:\(\s*u32\s*\)\s*)?\(\s*(' + IDENT + r')\s*&\s*(' + MASK + r')\s*\)\s*<\s*(.+?)\s*',
                            tail[1], re.S)
        if not cond:
            continue
        var, mask, limit = cond[1], cond[2], cond[3]
        narrow = MASKS[mask.lower() if mask.lower() in MASKS else mask]
        inner = clean[start+1:stop-1]
        step = re.search(r'\n[ \t]*' + var + r'\s*(?:\+=\s*1|\+\+)\s*;(?:\s*\n[ \t]*(' + IDENT + r')\s*=\s*' + var
                         + r'\s*&\s*' + MASK + r'\s*;)?\s*$', inner)
        if not step:
            continue
        copy = step[1]
        # m2c's guard around the loop, holding only an optional `copy = 0 & MASK;` and the loop
        guard_open = clean.rfind('{', opening, do.start() + opening)
        guard = re.search(r'\bif\s*\((.*)\)\s*$', clean[clean.rfind('\n', 0, guard_open):guard_open], re.S)
        between = clean[guard_open+1:opening+do.start()]
        guard_close = close(clean, guard_open, '{', '}')
        if not guard or not guard_close or clean[stop + tail.end():guard_close-1].strip():
            continue
        if between.strip() and not (copy and re.fullmatch(r'\s*' + copy + r'\s*=\s*0(?:\s*&\s*' + MASK + r')?\s*;\s*', between)):
            continue
        entry = re.fullmatch(r'\s*(.+?)\s*<\s*(.+?)\s*', guard[1], re.S)
        if not entry or _unwrap(entry[2]) != _unwrap(limit):
            continue
        if_start = clean.rfind('if', 0, guard_open)
        init = re.search(r'\n([ \t]*)' + var + r'\s*=\s*0\s*;\s*$', clean[:if_start])
        if not init:
            continue
        before = clean[opening+1:init.start()]
        left = entry[1].strip()
        if left != '0':
            zero = re.search(r'\bif\s*\(\s*' + re.escape(left) + r'\s*!=\s*0\s*\)\s*{', before)
            block_end = close(clean, opening + 1 + zero.end() - 1, '{', '}') if zero else None
            if (not zero or clean[block_end:init.start()].strip()
                    or not re.search(r'\breturn\s*;\s*$', clean[opening+1+zero.end():block_end-1])
                    or re.search(r'(?<![\w.>])' + re.escape(left) + r'\s*=(?!=)', clean[opening+1+zero.end():init.start()])):
                continue
        # The counter and its copy may not be read outside the loop.
        outside = clean[opening+1:init.start()] + clean[guard_close:end]
        names = [var] + ([copy] if copy else [])
        if any(re.search(r'(?<![\w.>])' + n + r'\b(?!\s+' + IDENT + r')', re.sub(r'\b' + IDENT + r'\s+\**' + n + r'\s*;', '', outside))
               for n in names):
            continue
        body = source[start+1:start+1+step.start()]
        if copy:
            body = re.sub(r'(?<![\w.>])' + copy + r'\b', var, body)
        body = re.sub(r'\(\s*' + var + r'\s*&\s*' + MASK + r'\s*\)', var, body)
        indent = init[1]
        loop = (f'{indent}for ({var} = 0; {var} < {source[stop+tail.start(1)+cond.start(3):stop+tail.start(1)+cond.end(3)]}; {var}++) {{'
                f'{_dedent(body)}\n{indent}}}')
        edits = [(init.start() + 1, guard_close, loop)]
        decl = re.search(r'(?m)^([ \t]*)(?:s32|u32|int|unsigned int|s16|u16)\s+(' + var + r')\s*;', clean[opening:init.start()])
        if not decl:
            continue
        edits.append((opening + decl.start(), opening + decl.end(), f'{decl[1]}{narrow} {var};'))
        if copy:
            copy_decl = re.search(r'(?m)^[ \t]*(?:s32|u32|int|unsigned int|s16|u16|u8)\s+' + copy + r'\s*;[ \t]*\n',
                                  clean[opening:init.start()])
            if copy_decl:
                edits.append((opening + copy_decl.start(), opening + copy_decl.end(), ''))
        result.append(('masked_counter_loop', _apply(source, edits)))
    return result


def unguarded_loops(source, name):
    """The same counter when it starts at a constant below a constant limit: gcc drops the entry test, and m2c writes
    `var = K; copy = K & 0xFF; do { ... } while ((u32) (var & 0xFF) < N);` with no guard. An N64 search loop over
    0x1E slots from 1 was 80% so after its loop was put right side out, and exact as `for (var = 1; var < 0x1E; ...)`."""
    found = _body(source, name)
    if not found:
        return []
    span, clean, opening, end = found
    result = []
    for do in re.finditer(r'\bdo\s*{', clean[opening:end]):
        start = opening + do.end() - 1
        stop = close(clean, start, '{', '}')
        tail = re.match(r'\s*while\s*\((.*?)\)\s*;', clean[stop:end], re.S) if stop else None
        if not tail:
            continue
        cond = re.fullmatch(r'\s*(?:\(\s*u32\s*\)\s*)?\(\s*(' + IDENT + r')\s*&\s*(' + MASK + r')\s*\)\s*<\s*'
                            r'(0[xX][0-9a-fA-F]+|\d+)[uU]?\s*', tail[1], re.S)
        if not cond:
            continue
        var, mask, limit = cond[1], cond[2], int(cond[3], 0)
        narrow = MASKS[mask.lower() if mask.lower() in MASKS else mask]
        inner = clean[start+1:stop-1]
        step = re.search(r'\n[ \t]*' + var + r'\s*(?:\+=\s*1|\+\+)\s*;(?:\s*\n[ \t]*(' + IDENT + r')\s*=\s*' + var
                         + r'\s*&\s*' + MASK + r'\s*;)?\s*$', inner)
        if not step:
            continue
        copy = step[1]
        # `var = K;` (and `copy = K & MASK;`) right before the loop, K a constant below the limit
        setup = re.search(r'\n([ \t]*)' + var + r'\s*=\s*(0[xX][0-9a-fA-F]+|\d+)\s*;[ \t]*\n'
                          + (r'[ \t]*' + copy + r'\s*=\s*(?:0[xX][0-9a-fA-F]+|\d+)(?:\s*&\s*' + MASK + r')?\s*;[ \t]*\n'
                             if copy else '') + r'[ \t]*$', clean[:opening + do.start()])
        if not setup or not 0 <= int(setup[2], 0) < limit:
            continue
        outside = clean[opening+1:setup.start()] + clean[stop + tail.end():end]
        names = [var] + ([copy] if copy else [])
        if any(re.search(r'(?<![\w.>])' + n + r'\b(?!\s+' + IDENT + r')',
                         re.sub(r'\b' + IDENT + r'\s+\**' + n + r'\s*;', '', outside)) for n in names):
            continue
        body = source[start+1:start+1+step.start()]
        if copy:
            body = re.sub(r'(?<![\w.>])' + copy + r'\b', var, body)
        body = re.sub(r'\(\s*' + var + r'\s*&\s*' + MASK + r'\s*\)', var, body)
        indent = setup[1]
        limit_text = source[stop + tail.start(1) + cond.start(3):stop + tail.start(1) + cond.end(3)]
        loop = (f'{indent}for ({var} = {setup[2]}; {var} < {limit_text}; {var}++) {{{body.rstrip()}\n{indent}}}')
        edits = [(setup.start() + 1, stop + tail.end(), loop)]
        decl = re.search(r'(?m)^([ \t]*)(?:s32|u32|int|unsigned int|s16|u16)\s+(' + var + r')\s*;', clean[opening:setup.start()])
        if not decl:
            continue
        edits.append((opening + decl.start(), opening + decl.end(), f'{decl[1]}{narrow} {var};'))
        if copy:
            copy_decl = re.search(r'(?m)^[ \t]*(?:s32|u32|int|unsigned int|s16|u16|u8)\s+' + copy + r'\s*;[ \t]*\n',
                                  clean[opening:setup.start()])
            if copy_decl:
                edits.append((opening + copy_decl.start(), opening + copy_decl.end(), ''))
        result.append(('masked_counter_loop', _apply(source, edits)))
    return result


def _dedent(body):
    """The do-while body was two levels deeper than the for loop that replaces the guard: one level out."""
    return '\n'.join(line[4:] if line.startswith('    ') else line for line in body.rstrip().split('\n'))


def variants(source, name):
    params = byte_parameters(source, name)
    loops = counter_loops(source, name) + unguarded_loops(source, name)
    both = [out for _, first in params for _, out in counter_loops(first, name) + unguarded_loops(first, name)]
    return ([('masked_counter_loop', out) for out in both] + loops + params)[:4]
