"""A loop's counter that the function reuses elsewhere, given a fresh counter of its own in a block around the loop.

`for (k = 0; k < p->n; k++) { }` where `k` is also the function's scratch value in a later loop and in switch arms:
one name is one pseudo for the whole function (GCC 2.x), so the loop's references and live range are added to the
pseudo that later holds the other values, and global.c ranks pseudos by `floor_log2(refs) * refs / live`. The target
kept the loop's counter in a temporary (`move $v1, $zero; addiu $v1, $v1, 1` inside the parts loop of a
618-instruction display-list interpreter, SN64 GCC 2.8.1 `-G0 -mips3 -O2 -mfp32`) where ours put it in the scratch
value's `$s0`: the same loop written `{ s32 k_1; for (k_1 = 0; k_1 < p->n; k_1++) { } }` was 1986 -> 1926 (and 1940
-> 1880 with the frame order fixed). Renaming it to another long-lived local that is free there (loop_role_rename's
move) gave nothing (1940 for every one tried), and local_web_split splits only plain `name = expr;` statements, never
a `for` header, so nothing offered the fresh name.

For every braced `for` loop whose header assigns `V` first (`for (V = ...;`), where `V` is a plain integer local
declared once at the function's top level, mentioned outside the loop too, not address-taken, not named by a
function-like macro, and dead after the loop (its next mention assigns it: a statement `V = ..` or an assignment in a
condition `if ((V = ..) <= 0)` that no `&&`, `||` or `?:` skips, outside any block opened after the loop; nor is it
read first in an enclosing loop's body), the loop is wrapped in `{ T V_n; <loop with V renamed V_n> }`. The program
is the same program. Declines for `goto` and `volatile`. A candidate rewrite; the exact judge decides.
"""
import re

from . import c_scan
from .integer_repair_support import edit, view
from .loop_role_rename import _DECL, _loops

FAMILY = 'loop_counter_block_scope'
FAMILIES = (FAMILY,)
LIMIT = 12
_FOR = re.compile(r'\bfor\s*\(\s*([A-Za-z_]\w*)\s*=(?!=)')


_PUNCT = re.compile(r'[()\[\];,]')
_LABEL = re.compile(r'\bcase\b[^:;{}]*:|\bdefault\s*:')


def _assignment_end(text, at):
    """The end of the expression assigned at `at` (just after `=`): the first `;` or `,` at depth zero, or an
    unbalanced `)`; None when there is none."""
    depth = 0
    for token in _PUNCT.finditer(text, at):
        c = token.group()
        if c in '([':
            depth += 1
        elif c in ')]':
            if depth == 0:
                return token.start()
            depth -= 1
        elif depth == 0:
            return token.start()
    return None


def assigned_first(text, var):
    """`var`'s old value is never read in `text`: its first mention assigns it (`var = expr`, the expression free of
    `var`, in a statement where no `&&`, `||` or `?` before it can skip it). An assignment inside a block that opened in
    `text` covers only the rest of that block, so the text after the block is checked again, and a `case` or `default`
    label after it is another way in, checked the same way from the label."""
    mention = re.search(rf'\b{var}\b', text)
    if not mention:
        return True
    assign = re.compile(rf'{var}\s*=(?!=)').match(text, mention.start())
    if not assign:
        return False
    before = text[:mention.start()]
    head = max(before.rfind(';'), before.rfind('{'), before.rfind('}'))
    if re.search(r'&&|\|\||\?', before[head + 1:]):
        return False
    end = _assignment_end(text, assign.end())
    if end is None or re.search(rf'\b{var}\b', text[assign.end():end]):
        return False
    outer, block = -1, c_scan.enclosing_block(text, mention.start(), 0)
    while block >= 0:
        outer, block = block, c_scan.enclosing_block(text, block, 0)
    close = c_scan.close(text, outer) if outer >= 0 else len(text)
    if close < 0:
        return False
    for label in _LABEL.finditer(text, end, close):  # another way in, past the assignment
        if not assigned_first(text[label.end():], var):
            return False
    return outer < 0 or assigned_first(text[close + 1:], var)


def _fresh(var, taken):
    n = 1
    while f'{var}_{n}' in taken:
        n += 1
    return f'{var}_{n}'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    if re.search(r'\bvolatile\b', body) or re.search(r'\bgoto\b', body):
        return []
    macro_names = set()
    for text in re.findall(r'(?m)^\s*#\s*define\s+\w+\(([^\n]*(?:\\\n[^\n]*)*)', source):
        macro_names |= set(re.findall(r'[A-Za-z_]\w*', text))
    declared = {}
    for decl in _DECL.finditer(clean, lo, hi):
        if clean[lo:decl.start()].count('{') - clean[lo:decl.start()].count('}') == 0:
            if decl.group(2) in declared:
                declared[decl.group(2)] = None  # declared twice: shadowing, leave it
            else:
                declared[decl.group(2)] = re.sub(r'\s+', ' ', decl.group(1))
    taken = set(re.findall(r'[A-Za-z_]\w*', source))
    loops = _loops(clean, lo, hi)
    out = []
    for start, _, end in loops:
        header = _FOR.match(clean, start)
        if not header:
            continue
        var = header.group(1)
        kind = declared.get(var)
        if not kind or var in macro_names or re.search(rf'&\s*{var}\b', body):
            continue
        outside = clean[lo:start] + clean[end:hi]
        if len(re.findall(rf'\b{var}\b', outside)) < 2:
            continue  # only its declaration and this loop name it: a fresh name changes nothing
        later = clean[end:hi]
        if re.search(rf'\b{var}\b', later) and not assigned_first(later, var):
            continue
        if any(s < start and end <= e and not assigned_first(clean[b + 1:e], var) for s, b, e in loops):
            continue
        fresh = _fresh(var, taken)
        line = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:start]).group()
        if source[line:start].strip():
            continue  # the loop shares its line with other code: no block to wrap cleanly
        loop = re.sub(rf'\b{var}\b', fresh, source[start:end])
        loop = loop.replace('\n', '\n    ')
        wrapped = f'{{\n{indent}    {kind} {fresh};\n{indent}    {loop}\n{indent}}}'
        text = edit(source, [(start, end, wrapped)])
        if text != source and all(text != t for _, t in out):
            out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
