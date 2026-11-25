"""One local per value the game kept in one place: arm scratch locals folded into the local that takes over, and a
scratch reused in several arms given one name per arm, together.

m2c invents a temporary for each arm that computes a narrow value (`temp_s4 = (x & 0x3F) & 0xFF;`) and copies it into
the function-wide local afterwards (`var_s4 = lo5;`); the game wrote one variable. GCC 2.7.2 allocates registers by
priority over whole-function pseudos: an arm-local temporary is a block-local quantity that local-alloc puts in the first
callee-saved register it finds, which takes that register from the function-wide pseudos allocated later (`$s0` for a
byte copy, and the function's argument and record pointers then shift by one: 8692 -> 8456 on a 616-instruction audio
command builder, with the next step). Folding the scratch into the function-wide local gives that local the scratch's
references (its priority rises past the others'), and a scratch shared by the head of the function and by the arms gets
a name per arm so each arm's value is a block-local quantity again, as the target's arms have it (`lo5`: `$s0` there too).
Neither half alone helps (10600 and 8801 against 8676 for the pair together measured 8456); the family offers the pair as
one child, and each half as its own.

`scratch_merge`: a narrow local B (`u8`/`s8`/`u16`/`s16`) whose textually last mention is the right side of a plain
assignment to another local A (`A = expr(B);`), and that no `&B` or `&A` is taken and no label sits between B's first
mention and that assignment, is renamed A everywhere; B's declaration goes, and A takes B's narrow type (one child) or
keeps its own (another). The check is textual: B's value is dead after the copy and A's old value is overwritten by it.
`scratch_arm_split`: a local S mentioned in the head of the function and in two or more braced arms, whose first mention
in each arm is an assignment `S = ...;` and that is not mentioned after the first arm outside the arms, gets a local per
arm (`S_a`, `S_b`, ..., same type). Whether the textual order is the execution order (a loop, a backward `goto`) is not
proved: a function with a backward jump label is left alone. Every child is judged."""
import re

from .integer_repair_support import edit, view

FAMILY_MERGE = 'scratch_merge'
FAMILY_SPLIT = 'scratch_arm_split'
FAMILY = 'arm_scratch_merge'
FAMILIES = (FAMILY_MERGE, FAMILY_SPLIT, FAMILY)

_IDENT = r'[A-Za-z_]\w*'
_NARROW = ('u8', 's8', 'u16', 's16')
_DECL = re.compile(r'(?m)^([ \t]*)((?:unsigned\s+(?:char|short|int)|unsigned|signed\s+(?:char|short|int)|[su](?:8|16|32)|'
                   r'int|char|short)\s+)(' + _IDENT + r')[ \t]*;[ \t]*\n')


def _mentions(clean, name, lo, hi):
    return [m for m in re.finditer(r'(?<![\w.>])' + re.escape(name) + r'\b', clean[lo:hi]) if (lo + m.start())]


def _declarations(part):
    return {m[3]: (m.start(), m.end(), m[2].strip()) for m in _DECL.finditer(part.clean, part.opening, part.end)}


def _locals_ok(part, *names):
    body = part.clean[part.opening:part.end]
    for name in names:
        if re.search(r'&\s*' + re.escape(name) + r'\b', body):
            return False
    return True


def _python_top_statements(clean, lo, hi):
    """(start, end) of each statement at the block's own depth between `lo` (just after its `{`) and `hi`."""
    out, depth, start = [], 0, lo
    for index in range(lo, hi):
        char = clean[index]
        if char in '({[':
            depth += 1
        elif char in ')}]':
            depth -= 1
        elif char == ';' and depth == 0:
            out.append((start, index + 1))
            start = index + 1
        elif char == '}' and depth == 0:
            start = index + 1
    return out


_top_statements = _python_top_statements
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_statements(clean, lo, hi):
        found = _scan.statements_mixed(clean, lo, hi)
        return _python_top_statements(clean, lo, hi) if found is NotImplemented else found


def _innermost_block(blocks, first, last):
    found = None
    for lo, hi in blocks:
        if lo < first and last < hi and (found is None or lo > found[0]):
            found = (lo, hi)
    return found


def _merge_pairs(part):
    """[(B, A)] for every narrow B that one of two evidence rules folds into A: the textually last mention of B is the
    right side of `A = expr(B);` (a copy), or all of B sits in one block whose own level assigns `A = ...;` after B's last
    mention, with A not mentioned in that block before the assignment (B dead, A not yet in use)."""
    decls = _declarations(part)
    blocks = _arm_blocks(part)
    pairs = []
    for b, (d0, d1, kind) in decls.items():
        if kind not in _NARROW or not _locals_ok(part, b):
            continue
        refs = [d1 + m.start() for m in re.finditer(r'(?<![\w.>])' + re.escape(b) + r'\b', part.clean[d1:part.end])]
        if len(refs) < 2:
            continue
        first, last = refs[0], refs[-1]
        if re.search(r'\b' + _IDENT + r'\s*:(?!:)|\bgoto\b', part.clean[first:last]):
            copy = True  # a jump between the mentions: only the copy rule can say it is dead
        else:
            copy = False
        begin = max(part.clean.rfind(';', 0, last), part.clean.rfind('{', 0, last), part.clean.rfind('}', 0, last)) + 1
        end = part.clean.find(';', last)
        head = re.match(r'\s*(' + _IDENT + r')\s*=(?!=)\s*(.*)', part.clean[begin:end], re.S) if end >= 0 else None
        if head and head[1] != b and head[1] in decls and _locals_ok(part, head[1]) and re.search(
                r'(?<![\w.>])' + re.escape(b) + r'\b', head[2]):
            pairs.append((b, head[1]))
            continue
        if copy:
            continue
        block = _innermost_block(blocks, first, last)
        if not block:
            continue
        for start, stop in _top_statements(part.clean, block[0] + 1, block[1]):
            if start <= last:
                continue
            assign = re.match(r'\s*(' + _IDENT + r')\s*=(?!=)', part.clean[start:stop])
            if assign and assign[1] != b and assign[1] in decls and _locals_ok(part, assign[1]) \
                    and not re.search(r'(?<![\w.>])' + re.escape(assign[1]) + r'\b', part.clean[block[0]:start]):
                pairs.append((b, assign[1]))
            break
    return pairs


def _merge(source, part, pairs, retype='narrow'):
    decls = _declarations(part)
    edits = []
    renames = {}
    for b, a in pairs:
        renames.setdefault(b, a)
    if not renames:
        return None
    for b, a in renames.items():
        d0, d1, kind = decls[b]
        edits.append((d0, d1, ''))
        for m in re.finditer(r'(?<![\w.>])' + re.escape(b) + r'\b', part.clean[d1:part.end]):
            edits.append((d1 + m.start(), d1 + m.end(), a))
        a0, a1, akind = decls[a]
        if retype == 'narrow' or (retype == 'signed' and akind in ('s32', 'int', 'signed int')):
            edits.append((a0, a1, source[a0:a1].replace(akind, kind, 1)))
    return edit(source, edits)


def _arm_blocks(part):
    """The braced blocks inside the function (depth >= 2, outermost first), as (open, close)."""
    out = []
    clean = part.clean
    index = part.opening + 1
    depth = 1
    stack = []
    while index < part.end - 1:
        char = clean[index]
        if char == '{':
            depth += 1
            stack.append(index)
        elif char == '}':
            depth -= 1
            if stack:
                out.append((stack.pop(), index))
        index += 1
    return sorted(out)


def _split(source, part):
    decls = _declarations(part)
    blocks = _arm_blocks(part)
    if re.search(r'\bgoto\b', part.clean[part.opening:part.end]):
        # forward jumps into shared tails keep the textual order; a backward label does not
        labels = [m for m in re.finditer(r'(?m)^[ \t]*(' + _IDENT + r')[ \t]*:(?!:)', part.clean[part.opening:part.end])]
        for label in labels:
            at = part.opening + label.start()
            if re.search(r'\bgoto\s+' + re.escape(label[1]) + r'\b', part.clean[at:part.end]):
                return None
    out = []
    for s, (d0, d1, kind) in decls.items():
        if not _locals_ok(part, s):
            continue
        refs = [m for m in re.finditer(r'(?<![\w.>])' + re.escape(s) + r'\b', part.clean[d1:part.end])]
        positions = [d1 + m.start() for m in refs]
        if len(positions) < 4:
            continue
        arms = []
        for lo, hi in blocks:
            inside = [p for p in positions if lo < p < hi]
            if not inside or any(lo < a[0] and a[1] < hi for a in arms):
                continue
            first = inside[0]
            statement = re.match(re.escape(s) + r'\s*=(?!=)[^;]*;', part.clean[first:hi])
            if not statement:
                continue
            if any(a[0] < lo and hi < a[1] for a in arms):
                continue
            arms.append((lo, hi, inside))
        arms = [a for a in arms if not any(b is not a and b[0] < a[0] and a[1] < b[1] for b in arms)]
        if len(arms) < 2:
            continue
        head = [p for p in positions if not any(lo < p < hi for lo, hi, _ in arms)]
        first_arm = min(a[0] for a in arms)
        if not head or any(p > first_arm for p in head):
            continue
        suffixes = 'abcdefghij'
        edits = []
        for index, (lo, hi, inside) in enumerate(arms[:len(suffixes)]):
            new = f'{s}_{suffixes[index]}'
            for p in inside:
                edits.append((p, p + len(s), new))
        decl = source[d0:d1]
        extra = ''.join(decl.replace(s, f'{s}_{suffixes[i]}', 1) for i in range(min(len(arms), len(suffixes))))
        edits.append((d1, d1, extra))
        out.append(edit(source, edits))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    pairs = _merge_pairs(part)
    texts = []
    if pairs:
        for retype in ('narrow', 'own', 'signed'):
            text = _merge(source, part, pairs, retype)
            if text and text not in texts:
                texts.append(text)
    for text in texts:
        out.append((FAMILY_MERGE, text))
    for text in _split(source, part) or []:
        out.append((FAMILY_SPLIT, text))
    # both halves as one child: split the merged text (the merge changes no arm's first mention)
    for base in texts:
        again = view(base, name)
        for text in (_split(base, again) if again else None) or []:
            out.append((FAMILY, text))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 260}
