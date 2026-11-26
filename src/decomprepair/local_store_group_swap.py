"""Two neighbouring groups of stores to two different locals (`max[0..2] = K; min[0..2] = L;`) written in the other
order, as whole groups.

A bounding-box pass starts by filling two local arrays with their sentinels, three stores each. The target (a
618-instruction display-list interpreter, SN64 GCC 2.8.1 `-G0 -mips3 -O2 -mfp32`) loads the first group's constant
into `$v0` and stores the group at 0x40 first; ours had the constants in each other's registers and the other array
stored first: six frame rows and four constant rows. The scheduler keeps stores to one array in the source's order
and the allocator numbers the constants' pseudos by first use, so which group is written first decides both. The two
groups swapped (`min` before `max`) was 1986 -> 1940. Nothing offered it: `assignment_run_move` and `store_run_order`
move one statement at a time and treat any store through an index as a barrier for every other store, and
`repeated_block_order_swap` swaps only plain variables.

In a run of consecutive one-line assignments at one indent (`base = v;`, `base[i] = v;`, `base.f = v;`, no call,
`++`/`--` or compound assignment), consecutive lines with the same base form a group. Two neighbouring groups are
swapped when at least one has two or more lines, both bases are locals of the function (declared in it, neither a
pointer nor address-taken; an array's every mention indexes it, so it never decays into a pointer that could alias the
other) and neither group mentions the other's base. Locals declared apart cannot overlap, so the program is the same
program. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'local_store_group_swap'
FAMILIES = (FAMILY,)
LIMIT = 12
_KEYWORDS = {'return', 'goto', 'break', 'continue', 'case', 'else', 'do', 'sizeof', 'typedef', 'extern', 'static'}
_DECLARATION = re.compile(r'(?m)^[ \t]*((?:[A-Za-z_]\w*[ \t]+)+)(\**)[ \t]*([A-Za-z_]\w*)[ \t]*((?:\[[^\]\n]*\])*)[ \t]*;[ \t]*$')
_STORE = re.compile(r'^(?P<indent>[ \t]*)(?P<base>[A-Za-z_]\w*)(?P<sub>(?:\[[^\]\n;]*\]|\.[A-Za-z_]\w*)*)[ \t]*=(?!=)'
                    r'[ \t]*(?P<value>[^;{}\n]+);[ \t]*$')
_CALL = re.compile(r'\b(?!(?:sizeof)\b)[A-Za-z_]\w*\s*\(')


def _locals(body):
    """{name: is_array} of the locals the function body declares (not pointers)."""
    found = {}
    for decl in _DECLARATION.finditer(body):
        words = decl.group(1).split()
        if words[0] in _KEYWORDS or decl.group(2):
            continue
        name = decl.group(3)
        if name in found:
            found[name] = None  # declared twice: shadowing, leave it
        else:
            found[name] = bool(decl.group(4))
    return {name: array for name, array in found.items() if array is not None}


def _safe(body, name, array):
    """`name` never has its address taken nor (an array) is used without an index."""
    if re.search(rf'&\s*{name}\b', body):
        return False
    if array:
        for mention in re.finditer(rf'(?<!\.)(?<!->)\b{name}\b', body):
            after = body[mention.end():mention.end() + 40]
            if re.match(r'\s*\[', after):
                continue
            line_start = body.rfind('\n', 0, mention.start()) + 1
            line_end = body.find('\n', mention.end())
            if _DECLARATION.match(body[line_start:line_end if line_end >= 0 else len(body)]):
                continue
            return False
    return True


def _store(line):
    found = _STORE.match(line)
    if not found or '++' in line or '--' in line:
        return None
    if _CALL.search(found.group('value')) or _CALL.search(found.group('sub')):
        return None
    return found


def _reads(group, name):
    return any(re.search(rf'\b{name}\b', item[3].group('sub') + item[3].group('value')) for item in group)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    if re.search(r'\bvolatile\b', body):
        return []
    local = _locals(body)
    safe = {n for n, array in local.items() if _safe(body, n, array)}
    # lines of the body with their offsets in `source`
    rows, at = [], lo
    for text in clean[lo:hi].split('\n'):
        rows.append((at, at + len(text), text))
        at += len(text) + 1
    runs, run = [], []
    for start, end, text in rows:
        found = _store(text)
        if found and run and found.group('indent') == run[-1][3].group('indent'):
            run.append((start, end, text, found))
            continue
        if len(run) >= 2:
            runs.append(run)
        run = [(start, end, text, found)] if found else []
    if len(run) >= 2:
        runs.append(run)
    out = []
    for run in runs:
        groups = []
        for item in run:
            if groups and groups[-1][0] == item[3].group('base'):
                groups[-1][1].append(item)
            else:
                groups.append((item[3].group('base'), [item]))
        for (a, first), (b, second) in zip(groups, groups[1:]):
            if a not in safe or b not in safe or max(len(first), len(second)) < 2:
                continue
            if _reads(second, a) or _reads(first, b):
                continue
            start, end = first[0][0], second[-1][1]
            lines = [source[s:e] for s, e, _, _ in second] + [source[s:e] for s, e, _, _ in first]
            text = edit(source, [(start, end, '\n'.join(lines))])
            if text != source and all(text != t for _, t in out):
                out.append((FAMILY, text))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
