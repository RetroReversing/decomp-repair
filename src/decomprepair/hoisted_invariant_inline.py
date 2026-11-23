"""A loop invariant m2c named after the register or stack slot the compiler hoisted it into, written where it is used.

gcc 2.x's loop pass moves a loop-invariant expression out of the loop (`arg12 - 1`, `arg4 >> 1`) into a register or a
spill slot, and m2c prints what it sees: `temp_s1 = arg12 - 1;` before the loops and `temp_s1` at every use inside them,
`sp14 = (u32) arg4 >> 1;` for the value that went to the stack. The game wrote the expression at each use and the loop
pass did the hoisting, so the draft's named local is a second variable the original never had: it changes the first
scheduler's and the allocator's view of the loop (a pseudo set once, before the loop, with its own live range) before
anything else about the loop is right. On a 369-instruction N64 display-list builder (KMC gcc 2.7.2) writing three such
locals (`temp_s1`, `temp_s0`, `sp14`) where they were read took the judge from 16710 to 13330, the largest single
step after the commands became the SDK's macros. No family wrote an invariant back: `single_use_inline` wants one use,
`parameter_copy_drop` a copy of a parameter, `param_loop_carrier` only the one that goes to the stack.

A candidate is a local assigned exactly once, by a plain statement `L = E;` before a loop, where E is built from
parameters, literals and operators only (no call, no memory read, no float), the parameters it names are never
assigned anywhere, L is not address-taken, and at least one read of L is inside a loop that starts after the
assignment. Every read becomes `(E)` and the assignment and the declaration go. The family offers all such locals at
once (they only pay off together: each alone leaves the others' live ranges where they were) and each one alone.
"""
import re

from .display_cursor_record_repairs import _statements
from .integer_repair_support import IDENT, edit, view

FAMILY = 'hoisted_invariant_inline'
FAMILIES = (FAMILY,)
LIMIT = 6
PLAIN = re.compile(rf'(?P<n>{IDENT})\s*=(?!=)\s*(?P<v>[^;]+);\Z')
DECLARATION = re.compile(rf'(?:{IDENT}\s+)+\**\s*(?P<n>{IDENT})\s*;\Z')
KEYWORDS = {'sizeof', 'if', 'else', 'while', 'do', 'for', 'return'}
TYPES = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'unsigned', 'long', 'short', 'char', 'signed'}
LOOP = re.compile(r'\b(?:do|while|for)\b')


def _assigned(body, name):
    return re.findall(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.>])(?:\+\+|--)\s*{re.escape(name)}\b|'
                      rf'(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', body)


def _loops(clean, start, end):
    """(start of the body brace, its closing brace) of every do/while/for loop."""
    out = []
    for hit in LOOP.finditer(clean, start, end):
        if hit.group() == 'while' and re.match(r'\s*\([^;{}]*\)\s*;', clean[hit.end():hit.end() + 200]):
            continue  # the `while (...);` that ends a do loop
        brace = clean.find('{', hit.end(), end)
        if brace < 0 or clean[hit.end():brace].count(';') > 0 and hit.group() != 'for':
            continue
        depth, i = 0, brace
        while i < end:
            depth += clean[i] == '{'
            depth -= clean[i] == '}'
            if depth == 0:
                break
            i += 1
        out.append((brace, i))
    return out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    signature = re.search(rf'\b{re.escape(name)}\s*\((?P<p>[^)]*)\)', clean[:part.opening + 1])
    if not signature or re.search(r'\b(?:volatile|asm|goto)\b', clean[part.opening:part.end]):
        return []
    parameters = set(re.findall(rf'({IDENT})\s*(?:,|\Z)', signature['p'])) - TYPES
    body = clean[start:end]
    spans = _statements(clean, start, end)
    loops = _loops(clean, start, end)
    found = []
    for a, b in spans:
        text = clean[a:b]
        m = PLAIN.match(text)
        if not m or DECLARATION.match(text):
            continue
        local, value = m['n'], m['v'].strip()
        if local in parameters or len(_assigned(body, local)) != 1 or re.search(rf'&\s*{re.escape(local)}\b', body):
            continue
        names = set(re.findall(IDENT, value)) - TYPES
        if not names <= parameters or any(_assigned(body, p) for p in names) or re.search(r'[.]\d|\d[.]|\d[fF]\b|->|\[|\*\s*\w|\(\s*(?:f32|f64|float|double)', value):
            continue
        if re.search(rf'\b(?!(?:{"|".join(TYPES)})\b){IDENT}\s*\(', value) or len(value) > 60:
            continue
        reads = [r for r in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[b:end]) if clean[b + r.end():b + r.end() + 1] != '(']
        inside = [r for r in reads if any(lo < b + r.start() < hi and lo > b for lo, hi in loops)]
        if not reads or not inside or any(lo < a < hi for lo, hi in loops):
            continue
        found.append((a, b, local, value, [b + r.start() for r in reads]))
    if not found:
        return []
    out = []
    choices = [found] if len(found) > 1 else []
    choices += [[c] for c in found]
    for chosen in choices:
        edits = []
        for a, b, local, value, reads in chosen:
            atom = re.fullmatch(rf'{IDENT}|\d+|0[xX][0-9a-fA-F]+', value)
            for r in reads:
                edits.append((r, r + len(local), value if atom else f'({value})'))
            line = source.rfind('\n', 0, a) + 1
            stop = source.find('\n', b)
            whole = not source[line:a].strip() and not source[b:stop if stop >= 0 else len(source)].strip()
            edits.append((line, stop + 1, '') if whole else (a, b, ''))
            for d in spans:
                dm = DECLARATION.fullmatch(clean[d[0]:d[1]])
                if dm and dm['n'] == local:
                    line = source.rfind('\n', 0, d[0]) + 1
                    stop = source.find('\n', d[1])
                    edits.append((line, stop + 1, ''))
        text = edit(source, edits)
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
