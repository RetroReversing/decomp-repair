"""A switch arm's reloaded first value restored, with each loaded value in a local of its own.

A search that was chasing a register left this shape in an arm that loads three table entries (one arm of a
format switch: the same arm exists for the other element sizes):

    tmp = T[p[1]];   out[0] = tmp;               /* the first value                          */
    v = T[p[2]];     out[1] = (u8) v;            /* the second                                */
    tmp = T[p[3]];                               /* the third, in the first one's local       */
    a = inline_fn(T, p[1]);                      /* "reload the first": a dead store ...      */
    a = (u8) tmp;                                /* ... overwritten by the third (wrong value) */
    b = v & 0xFF;  v = tmp & 0xFF;  out[2] = tmp;

The arm is not the program: the call's first argument is the first value, and the sibling arms of the same switch keep
each loaded value in a local of its own. The overwrite is a dead stray, the helper's value is the one the call took
(`T[p[1]] & 0xFF`, and the first value is what the arm loaded into `tmp` first), and the scratch locals that hold two
values one after the other (`tmp`, `v`) are one local per value:

    { u8 first = T[p[1]]; u8 second;
      out[0] = first; second = T[p[2]]; out[1] = second;
      tmp = T[p[3]];  a = first & 0xFF;  b = second & 0xFF;  v = tmp & 0xFF;  out[2] = tmp; }

With the block-scoped `u8` locals the allocator gives the first value a register of its own (`lbu $a0; andi $a2, $a0,
0xff`), as the target has it; it was the last step (20 -> 0) of a 359-instruction interpreter, after the cursor folds
(`cursor_lockstep_fold`) and the loop's opcode local (`dispatch_byte_local`). The child is a hypothesis about the
program the arm should have been; the exact judge decides.

`variants` offers it for each brace-free, straight-line arm that has the dead pair `X = h(A, B); X = <expr>;` where `h`
is an inline `return a[b] & 0xFF;` and the arm assigns `A[B]` to a local earlier. The webs of every scratch local the arm
assigns more than once (all but its last, which leaves the arm) become `u8` locals when what they load is a byte."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'arm_reload_restore'
FAMILIES = (FAMILY,)
LABEL = re.compile(r'\b(?:case\s+[^:;{}]+|default)\s*:')
STOP = re.compile(r'\b(?:if|else|for|while|do|switch|goto|return|continue)\b|[{}]')
NAMES = ('first', 'second', 'third', 'fourth')


def _reloaders(clean):
    """name -> (array parameter, index parameter) for `T name(u8 *a, u8 b) { return a[b] & 0xFF; }`."""
    found = {}
    for hit in re.finditer(rf'\b({IDENT})\s*\(([^)]*)\)\s*{{\s*return\s+({IDENT})\s*\[\s*({IDENT})\s*\]\s*&\s*(?:0xFF|0xff|255)\s*;\s*}}', clean):
        params = [re.search(rf'({IDENT})\s*$', part.strip()) for part in hit[2].split(',')]
        if len(params) == 2 and all(params) and (hit[3], hit[4]) == (params[0][1], params[1][1]):
            found[hit[1]] = True
    return found


def _python_split(clean, lo, hi):
    """[(start, end)] of the `;`-terminated statements of clean[lo:hi] (no braces inside: the caller checked)."""
    out, at, depth = [], lo, 0
    for i in range(lo, hi):
        depth += (clean[i] in '([') - (clean[i] in ')]')
        if clean[i] == ';' and depth == 0:
            while at < i and clean[at].isspace():
                at += 1
            out.append((at, i + 1))
            at = i + 1
    return out


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(clean, lo, hi):
        found = _scan.split_statements(clean, lo, hi)
        return _python_split(clean, lo, hi) if found is NotImplemented else found


def _norm(text):
    return re.sub(r'\s+', '', text)


def _pointer_types(clean):
    found = {}
    for hit in re.finditer(rf'(?m)(?:^|[(,])\s*(?:register\s+|const\s+)*((?:unsigned\s+)?\w+)\s*\*\s*({IDENT})\b', clean):
        found[hit[2]] = hit[1]
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    whole = _blank(source)
    helpers = _reloaders(whole)
    if not helpers:
        return []
    clean = part.clean
    base, end = part.opening + 1, part.end - 1
    pointers = _pointer_types(clean[:end])
    labels = [(base + m.start(), base + m.end()) for m in LABEL.finditer(clean[base:end])]
    out = []
    for index, (_, label_end) in enumerate(labels):
        limit = labels[index + 1][0] if index + 1 < len(labels) else end
        brk = re.search(r'\bbreak\s*;', clean[label_end:limit])
        stop = label_end + brk.start() if brk else limit
        chunk = clean[label_end:stop]
        if STOP.search(chunk) or not chunk.strip():
            continue
        statements = [(a, b) for a, b in _split(clean, label_end, stop)]
        texts = [clean[a:b] for a, b in statements]
        child = _restore(source, clean, statements, texts, helpers, pointers, label_end, stop)
        if child:
            out.append((FAMILY, child))
    return out


def _restore(source, clean, statements, texts, helpers, pointers, chunk_start, chunk_end):
    assign = [re.fullmatch(rf'({IDENT})\s*=\s*([^;]*);', text) for text in texts]
    for i in range(len(texts) - 1):
        first, second = assign[i], assign[i + 1]
        if not first or not second or first[1] != second[1] or re.search(rf'\b{first[1]}\b', second[2]):
            continue
        call = re.fullmatch(rf'({IDENT})\s*\(\s*({IDENT})\s*,\s*([^;]*)\)', first[2].strip())
        if not call or call[1] not in helpers:
            continue
        wanted = _norm(f'{call[2]}[{call[3]}]')
        load = next((k for k in range(i) if assign[k] and _norm(assign[k][2]) == wanted), None)
        if load is None:
            continue
        # the webs of every local the chunk assigns more than once, but its last web
        webs, rename = {}, []
        for k, hit in enumerate(assign):
            if hit:
                webs.setdefault(hit[1], []).append(k)
        names = iter(NAMES)
        declared, edits = [], []
        order = sorted((ks[j], var, j) for var, ks in webs.items() if len(ks) > 1 for j in range(len(ks) - 1))
        for k, var, j in order:
            if var == first[1]:
                continue
            load_text = assign[k][2].strip()
            pointer = re.match(rf'({IDENT})\s*\[', load_text)
            if not pointer or pointers.get(pointer[1]) not in ('u8', 'unsigned char'):
                continue
            nxt = webs[var][j + 1]
            lo, hi = statements[k][0], statements[nxt][0]
            local = next(names, None)
            if local is None:
                return None
            suffix = 0
            while re.search(rf'\b{local}\b', clean):
                suffix += 1
                local = f'{local.split("_")[0]}_{suffix}'
            for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[lo:hi]):
                edits.append((lo + m.start(), lo + m.end(), local))
            declared.append(local)
            rename.append((var, local, k, nxt))
        if not declared:
            continue
        # the value the dead store reloaded is the first loaded value: its local, then `& 0xFF`
        owner = next((local for var, local, k, nxt in rename if k == load), None)
        if owner is None:
            continue
        edits = [e for e in edits if not (statements[i][0] <= e[0] < statements[i + 1][1])]
        edits.append((statements[i][0], statements[i][1], f'{first[1]} = {owner} & 0xFF;'))
        low, high = statements[i + 1]
        line = source.rfind('\n', 0, low) + 1
        tail = source.find('\n', high)
        if not source[line:low].strip() and tail >= 0 and not source[high:tail].strip():
            low, high = line, tail + 1
        edits.append((low, high, ''))
        text = ' '.join(f'u8 {local};' for local in declared)
        first_at = statements[0][0]
        indent = source[source.rfind('\n', 0, first_at) + 1:first_at]
        indent = indent if not indent.strip() else '    '
        edits.append((chunk_start, chunk_start, ' {\n' + indent + text))
        brk = source.rfind('\n', 0, chunk_end) + 1
        pad = source[brk:chunk_end] if not source[brk:chunk_end].strip() else ''
        edits.append((chunk_end, chunk_end, '}\n' + pad))
        return edit(source, edits)
    return None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
