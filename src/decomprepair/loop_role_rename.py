"""A loop's own variable written as one of the function's long-lived locals that is free there: `for (x = 1; ..)` as `for (i = 1; ..)`.

The original often reuses a function-level variable as an inner loop's counter or temporary (the counter `i` of one
pass is the next pass's, a bit reader's destination is a table pass's scatter index). KMC GCC 2.7.2 gives each local
one pseudo for the whole function, so which variable a loop uses decides which pseudo's references and live range it
adds to, and global.c ranks pseudos by `floor_log2(refs) * refs / live`: a loop counter merged into the wrong variable
lifts that variable over its neighbours and every later colour moves (decomp-repair `block_temp_role_merge` merges
a block's own temporaries; this family moves a value between two function-level locals). On a 681-instruction bit-stream
decoder the code-length sort loop's counter written as the next pass's `i` (it had shared the decode loop's window
variable) was 595 -> 415, fuzz-checked on 600 generated streams against a clean transcription; one merge at a time is
how the role table was read, the subsets that pay off are searched by the caller's beam.

Renames every mention of `V` inside one loop statement (its header and body) to `W`, where both are plain integer
locals of the same declared type, the loop's first mention of `V` assigns it and `V` is not read after the loop before
it is assigned again (nor read first in an enclosing loop's body), and `W` is not mentioned in the loop and is dead
across it the same way. Declines for volatiles, address-taken names and names a function-like macro mentions.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'loop_role_rename'
FAMILIES = (FAMILY,)
LIMIT = 24

_TYPE = r'(?:unsigned\s+(?:int|short|char|long)|signed\s+(?:int|short|char)|s32|u32|s16|u16|s8|u8|int|long|short)'
_DECL = re.compile(rf'(?m)^[ \t]*({_TYPE})[ \t]+([A-Za-z_]\w*)[ \t]*;')
_KEYWORD = re.compile(r'\b(for|while)\s*\(|\bdo\s*\{')


def _first_mention_is_assignment(text, var):
    """The first mention of `var` in `text` is `var = <expression without var>`."""
    mention = re.search(rf'\b{var}\b', text)
    if not mention:
        return False
    assign = re.compile(rf'{var}\s*=(?!=)([^;]*)[;)]').match(text, mention.start())
    return bool(assign) and not re.search(rf'\b{var}\b', assign.group(1))


def _python_close(text, at, left, right):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == left) - (text[i] == right)
        if depth == 0:
            return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, at, left, right):
        found = _scan.close_every(text, at, left, right, False, None)
        return _python_close(text, at, left, right) if found is NotImplemented else found


def _loops(clean, lo, hi):
    """(statement start, body start, statement end) of every braced loop in the function."""
    out = []
    for key in _KEYWORD.finditer(clean, lo, hi):
        if key.group(1) == 'while' and re.search(r'}\s*$', clean[lo:key.start()]):
            continue  # the `while (..);` of a do-loop
        at = key.end() - 1
        if clean[at] == '(':
            shut = _close(clean, at, '(', ')')
            if shut is None:
                continue
            brace = re.compile(r'\s*\{').match(clean, shut + 1)
            if not brace:
                continue
            body = brace.end() - 1
            end = _close(clean, body, '{', '}')
            if end is None:
                continue
            out.append((key.start(), body, end + 1))
        else:
            end = _close(clean, at, '{', '}')
            tail = re.compile(r'\s*while\s*\(').match(clean, end + 1) if end is not None else None
            if not tail:
                continue
            shut = _close(clean, tail.end() - 1, '(', ')')
            if shut is None:
                continue
            out.append((key.start(), at, shut + 1))
    return out


def _dead_after(clean, var, start, end, hi, loops):
    later = clean[end:hi]
    if re.search(rf'\b{var}\b', later) and not _first_mention_is_assignment(later, var):
        return False
    for s, body, e in loops:
        if s < start and end <= e and not _first_mention_is_assignment(clean[body + 1:e], var):
            return False
    return True


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    if re.search(r'\bvolatile\b', body):
        return []
    macro_names = set()
    for text in re.findall(r'(?m)^\s*#\s*define\s+\w+\(([^\n]*(?:\\\n[^\n]*)*)', source):
        macro_names |= set(re.findall(r'[A-Za-z_]\w*', text))
    depth_zero = {}
    for decl in _DECL.finditer(clean, lo, hi):
        if clean[lo:decl.start()].count('{') - clean[lo:decl.start()].count('}') == 0:
            depth_zero[decl.group(2)] = re.sub(r'\s+', ' ', decl.group(1))
    names = [v for v in depth_zero if v not in macro_names and not re.search(rf'&\s*{v}\b', body)]
    if len(re.findall(r'\bgoto\b', body)):
        return []  # a jump into or out of a loop makes the text order no guide to liveness
    loops = _loops(clean, lo, hi)
    uses = {v: len(re.findall(rf'\b{v}\b', body)) for v in names}
    sites = []
    for start, _, end in loops:
        text = clean[start:end]
        for v in names:
            if not re.search(rf'\b{v}\b', text) or not _first_mention_is_assignment(text, v):
                continue
            if not _dead_after(clean, v, start, end, hi, loops):
                continue
            for w in sorted(names, key=lambda n: -uses[n]):
                if w == v or depth_zero[w] != depth_zero[v] or re.search(rf'\b{w}\b', text):
                    continue
                if not _dead_after(clean, w, start, end, hi, loops):
                    continue
                if re.search(rf'\b{w}\b', clean[lo:start]) is None:
                    continue  # a name not yet used before the loop is a fresh variable: local_web_split's work
                renamed = re.sub(rf'\b{v}\b', w, source[start:end])
                sites.append((uses[w], (start, end, renamed)))
    sites.sort(key=lambda item: -item[0])
    seen, out = set(), []
    for _, site in sites:
        text = edit(source, [site])
        if text != source and text not in seen:
            seen.add(text)
            out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
