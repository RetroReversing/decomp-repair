"""A second cursor started past a record's first element, rebased to where the target starts it.

m2c writes a triangle walk as a base pointer and a cursor that starts some bytes into the record and is stepped beside
it (`q = ((char *) p) + 4; ... q - 2 ... q + 0 ...; q += 6;`). Which offset the cursor starts at is the compiler's
choice in the target (`addiu $s0, $s3, 2`): loop.c keeps the source's pointers as givs, so a cursor started at +4
reads `-2(q)`/`0(q)` where the target reads `0(q)`/`2(q)`, and when the first element is read through the cursor too
(`q - 2` with `q = p + 2`) the base is not stepped at all, one pointer short. Children:

- the cursor rebased so the smallest offset read through it after the first element is 0 (`q = p + 2`, reads `+0`/`+2`);
- the read at the cursor's own start offset (`q - K`, the base's element 0) written through the base, with the base
  stepped beside the cursor if it was not.

A 1928-instruction collision sweep (KMC gcc 2.7.2): the base read 9242 -> 9209 on a byte-index walk, the rebase
9209 -> 9064 on a halfword one. One function; the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'cursor_offset_rebase'
BASE = 'cursor_offset_base_read'
FAMILIES = (FAMILY, BASE)

I = r'[A-Za-z_]\w*'
SIZE = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4}


def _reads(text, q):
    """[(start, end, kind, offset, form)] of the reads through q: `(((char *) q) + (OFF))`, `(((T *) q) - N)`."""
    out = []
    for m in re.finditer(r'\(\(\(char \*\) ' + q + r'\) \+ (?:\((-?\d+)\)|(\d+))\)', text):
        out.append((m.start(), m.end(), 'char', int(m[1] or m[2]), 'char'))
    for m in re.finditer(r'\(\(\((u8|s8|u16|s16|u32|s32) \*\) ' + q + r'\) - (\d+)\)', text):
        out.append((m.start(), m.end(), m[1], -int(m[2]) * SIZE[m[1]], 'typed'))
    return sorted(out)


def _spell(q, offset, read):
    if read[4] == 'typed':
        return '((%s *) (((char *) %s) + (%d)))' % (read[2], q, offset)
    return '(((char *) %s) + (%d))' % (q, offset) if offset < 0 else '(((char *) %s) + %d)' % (q, offset)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body_at = clean.find('{', span[0], span[1])
    body = source[body_at:span[1]]
    out = []
    for m in re.finditer(r'(?m)^([ \t]*)(' + I + r') = \(\(char \*\) (' + I + r')\) \+ (\d+);\n', body):
        q, p, start = m[2], m[3], int(m[4])
        step = re.search(r'(?m)^([ \t]*)' + q + r' \+= (\d+);\n', body[m.end():])
        if not step:
            continue
        loop = body[m.end():m.end() + step.start()]
        reads = _reads(loop, q)
        if len(reads) < 2:
            continue
        offsets = sorted({r[3] for r in reads})
        later = [o for o in offsets if o > -start]
        # the rebase: the smallest offset past element 0 becomes 0
        if later and later[0] != 0:
            shift = later[0]
            text = loop
            for r in reversed(reads):
                text = text[:r[0]] + _spell(q, r[3] - shift, r) + text[r[1]:]
            head = '%s%s = ((char *) %s) + %d;\n' % (m[1], q, p, start + shift)
            new = body[:m.start()] + head + text + body[m.end() + step.start():]
            out.append((FAMILY, source[:body_at] + new + source[span[1]:]))
        # the base read
        firsts = [r for r in reads if r[3] == -start]
        if firsts:
            text = loop
            kind = firsts[0][2] if firsts[0][4] == 'typed' else None
            for r in reversed(firsts):
                text = text[:r[0]] + ('((%s *) %s)' % (kind, p) if kind else '((char *) %s)' % p) + text[r[1]:]
            rest = body[m.end() + step.start():]
            stepped = re.search(r'(?m)^[ \t]*' + p + r' \+= ', text)
            head = body[:m.end()]
            if not stepped:
                decl = re.search(r'(?m)^([ \t]*)(\w+) \*' + p + r';', head)
                unit = SIZE.get(decl[2], 1) if decl else 1
                if decl and kind and int(step[2]) % unit:
                    # retype the base to the element it is read as, its one assignment cast to it
                    sets = list(re.finditer(r'(?m)^([ \t]*)' + p + r' = (?!\()', head))
                    if len(sets) != 1 or len(re.findall(r'\b' + p + r'\b', clean)) > 4:
                        continue
                    at = sets[0].end()
                    head = head[:at] + '(%s *) ' % kind + head[at:]
                    head = head[:decl.start()] + '%s%s *%s;' % (decl[1], kind, p) + head[decl.end():]
                    unit = SIZE[kind]
                if int(step[2]) % unit:
                    continue
                cut = step.end() - step.start()
                rest = rest[:cut] + '%s%s += %d;\n' % (step[1], p, int(step[2]) // unit) + rest[cut:]
            new = head + text + rest
            out.append((BASE, source[:body_at] + new + source[span[1]:]))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
