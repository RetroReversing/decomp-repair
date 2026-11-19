"""m2c's word-by-word copy of a small block, as the struct assignment it was.

A record copied with `*dst = *src` comes back from m2c as one store per word, sometimes with one word hoisted into a
temporary that a later call also uses:

    temp_a1 = M2C_FIELD(arg1, s32 *, 8);
    M2C_FIELD(temp_a0, s32 *, 0xC) = (s32) M2C_FIELD(arg1, s32 *, 0);
    M2C_FIELD(temp_a0, s32 *, 0x10) = (s32) M2C_FIELD(arg1, s32 *, 4);
    M2C_FIELD(temp_a0, s32 *, 0x14) = temp_a1;
    ...
    f(temp_a0, temp_a1);

Written word by word, `arg1` is used three times more than the game's source used it, and gcc 2.7.2 gave it the other
saved register: an N64 function had its two pointer parameters in swapped registers (94.4%). As one assignment of a
three-word record, with the temporary's later use reading the copied word, the registers came out as the game's
(95.3%). A hypothesis like every family's; the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'word_block_copy'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
FIELD = r'M2C_FIELD\(\s*(?P<{0}>' + IDENT + r')\s*,\s*s32\s*\*\s*,\s*(?P<{0}o>' + NUM + r')\s*\)'
STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)' + FIELD.format('d') + r'\s*=\s*(?:\(\s*s32\s*\)\s*)?(?:'
                   + FIELD.format('s') + r'|(?P<t>' + IDENT + r'))\s*;[ \t]*\n')
HOIST = re.compile(r'(?m)^[ \t]*(?P<t>' + IDENT + r')\s*=\s*' + FIELD.format('s') + r'\s*;[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    pos = opening + 1
    while (first := STORE.search(clean, pos, end)) is not None:
        pos = first.end()
        hoist = None
        before = clean.rfind('\n', opening, first.start() - 1) + 1
        if (h := HOIST.match(clean, before)) is not None and h.end() == first.start():
            hoist = h
        run, cursor = [first], first.end()
        while (nxt := STORE.match(clean, cursor)) is not None and nxt['indent'] == first['indent']:
            run.append(nxt)
            cursor = nxt.end()
        words = []
        for st in run:
            if st['t']:
                if not hoist or st['t'] != hoist['t']:
                    break
                words.append((st, hoist['s'], int(hoist['so'], 0)))
            else:
                words.append((st, st['s'], int(st['so'], 0)))
        # the longest run from the first store whose destination and source words are both consecutive
        prefix = []
        for k, w in enumerate(words):
            if (w[0]['d'] != run[0]['d'] or w[1] != words[0][1] or int(w[0]['do'], 0) != int(run[0]['do'], 0) + 4 * k
                    or w[2] != words[0][2] + 4 * k):
                break
            prefix.append(w)
        words = prefix
        if len(words) < 2 or (hoist and not any(w[0]['t'] for w in words)):
            continue
        n, dst, src, dbase, sbase = len(words), run[0]['d'], words[0][1], int(run[0]['do'], 0), words[0][2]
        record = f'__repair_words{n}'
        typedef = f'typedef struct {{ s32 w[{n}]; }} {record};\n'
        start = hoist.start() if hoist else first.start()
        stop = words[-1][0].end()
        line = (f'{first["indent"]}M2C_FIELD({dst}, {record} *, 0x{dbase:X}) = '
                f'*({record} *) ((s8 *) {src} + 0x{sbase:X});\n')
        text = source[:start] + line + source[stop:]
        if hoist:
            # later uses of the hoisted word read the copied destination word
            k = next(i for i, w in enumerate(words) if w[0]['t'])
            rest = text[start + len(line):]
            rest = re.sub(r'\b' + re.escape(hoist['t']) + r'\b', f'M2C_FIELD({dst}, s32 *, 0x{dbase + 4 * k:X})', rest)
            text = text[:start + len(line)] + rest
        at = source.rfind('\n', 0, span[0]) + 1
        text = text[:at] + (typedef if typedef not in text else '') + text[at:]
        result.append((FAMILY, text))
        if len(result) >= 3:
            break
    return result
