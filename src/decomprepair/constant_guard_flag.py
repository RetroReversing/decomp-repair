"""m2c's `if (0 == 0) goto L;` before dead stores, written back as the flag test the compiler kept, with its copies.

When a function tests a pointer it set to NULL at its start (`found = NULL; ... if (found == NULL) return 0; *out =
start; return 1;`) on a path cse can see, gcc 2.7.2 loads 0 into a register in a branch's delay slot but jump.c does
not thread the test away (`bc1tl ..., addu $t4, $zero, $zero` then `bnez $t4`). m2c reads that as

    if (0 == 0)
    {
      goto block_245;
    }
    <the copy, unreachable>
    goto block_247;           /* block_247: return 1; */
    ...
    block_245:
    return 0;

which compiles to nothing for the copy. The child writes the flag back: `flag = NULL;` at the top, the guard as `goto
check;`, and `check: if (flag == NULL) { return 0; } <the copy> return 1;` after the last return. A second child also
writes each struct copy of a frame array to a pointer (`*((V *) p) = *((V *) (&a));`) as element stores, which the
target had for another output on that function, and the moved copy as the word copy it was (frame_array_block_copy:
the target's `lw`/`sw`); they paid only together on a 1928-instruction collision sweep (KMC
gcc 2.7.2): the flag alone 12853 -> 13195, the element stores alone 12653, both 12008. One function; the judge
decides.
"""
import re

from . import frame_array_block_copy
from .csource import _blank, find

FAMILY = 'constant_guard_flag'
COMBINED = 'constant_guard_flag_stores'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'
GUARD = re.compile(r'(?m)^(?P<ind>[ \t]*)if \(0 == 0\)\s*\{\s*goto (?P<dead>' + I + r');\s*\}\n(?P<body>(?:(?![ \t]*goto\b)'
                   r'[^\n{}]*;\n)+)[ \t]*goto (?P<live>' + I + r');\n')


def _element_stores(text, source):
    """Each `*((V *) p) = *((V *) (&x));` with V a 3-float struct and x a #define'd array element, as three stores."""
    def fields(kind):
        m = re.search(r'typedef struct\s*\{\s*f32 (\w+);\s*f32 (\w+);\s*f32 (\w+);\s*\}\s*' + kind + r'\s*;', source)
        return m.groups() if m else None

    def repl(m):
        names = fields(m['kind'])
        if not names:
            return m[0]
        d = re.search(r'(?m)^#define\s+' + m['x'] + r'\s+(' + I + r')\s*\[\s*(\d+)\s*\]', source)
        if not d:
            return m[0]
        base, first = d[1], int(d[2])
        out = []
        for k in range(3):
            out.append('%s((Field_f32 *) (((char *) %s) + %d))->v = %s[%d];' % (m['ind'], m['p'], 4 * k, base, first + k))
        return '\n'.join(out)
    return re.sub(r'(?m)^(?P<ind>[ \t]*)\*\(\((?P<kind>' + I + r') \*\) (?P<p>' + I + r')\) = \*\(\((?P=kind) \*\) '
                  r'\(&(?P<x>' + I + r')\)\);', repl, text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = span[1]
    body = source[opening:end]
    m = GUARD.search(body)
    if not m or 'Field_f32' not in source:
        return []
    dead, live = m['dead'], m['live']
    live_at = re.search(r'(?m)^[ \t]*' + live + r':\s*\n(?P<ret>[ \t]*return [^;]+;)\n', body)
    dead_at = re.search(r'(?m)^(?P<ind>[ \t]*)' + dead + r':\s*\n[ \t]*return 0;\n', body)
    if not live_at or not dead_at or len(re.findall(r'\bgoto ' + dead + r';', body)) != 1:
        return []
    flag = 'found'
    while re.search(r'\b' + flag + r'\b', clean):
        flag += '_'
    ind = dead_at['ind']
    copies = [line.strip() for line in m['body'].strip('\n').split('\n')]
    tail = ('%sreturn 0;\n%scheck_%s:\n%sif (%s == NULL)\n%s{\n%s  return 0;\n%s}\n' % (ind, ind, flag, ind, flag, ind, ind, ind)
            + ''.join('%s%s\n' % (ind, c) for c in copies) + '%s%s\n' % (ind, live_at['ret'].strip()))
    text = body[:dead_at.start()] + tail + body[dead_at.end():]
    text = text[:m.start()] + '%sgoto check_%s;\n' % (m['ind'], flag) + text[m.end():]
    text = re.sub(r'(?m)^[ \t]*' + live + r':\s*\n', '', text, count=1)
    text = re.sub(r'\bgoto ' + live + r';', live_at['ret'].strip(), text)
    decl = '\n  void *%s;' % flag
    text = text[:1] + decl + text[1:]
    texts = [t for t in (_init(text, flag, r'[\w.>\[\]-]+\s*=(?!=)'), _init(text, flag, r'if\b')) if t]
    if not texts:
        return []
    out = []
    for text in texts:
        stored = _element_stores(text, source)
        whole = source[:opening] + stored + source[end:]
        # the moved copy as the word copy it compiles from, when it copies consecutive frame-array elements
        blocks = [t for _, t in frame_array_block_copy.variants(whole, name)
                  if re.search(r'check_%s:[^}]*\}[^}]*\*\(\(Block' % flag, t)]
        out += [(COMBINED, t) for t in blocks[:1]]
        if stored != text:
            out.append((COMBINED, whole))
    return out + [(FAMILY, source[:opening] + text + source[end:]) for text in texts]


def _init(text, flag, first):
    """`flag = NULL;` before the body's first top-level statement matching `first` (the first assignment, or the
    first `if` after the opening assignments, where the matched neighbour of the measured function sets it)."""
    depth, k = 0, 0
    for line in text.split('\n'):
        if depth == 1 and re.match(r'[ \t]+' + first, line):
            indent = re.match(r'[ \t]*', line)[0]
            return text[:k] + '%s%s = NULL;\n' % (indent, flag) + text[k:]
        depth += line.count('{') - line.count('}')
        k += len(line) + 1
    return None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
