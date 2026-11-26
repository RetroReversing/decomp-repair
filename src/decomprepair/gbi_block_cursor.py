"""Display-list commands written through a block-scoped cursor copy, as libultra's Gbi macros expand.

`gDPPipeSync(gfx++)` expands to `{ Gfx *_g = (Gfx *)(gfx++); _g->words.w0 = ..; _g->words.w1 = ..; }`: every command
gets a pointer of its own, born and dead in its block. Drafts and saved bests write the same stores straight through the
cursor (`gfx->w0 = A; gfx->w1 = B; gfx++;`) or through one function-wide pointer (`dl = gfx++; dl->w0 = A; ..`), which
is a single pseudo for every command: global.c then ranks it with the long-lived values and the commands' copies and
temporaries take other registers. A 618-instruction N64 display-list interpreter (SN64 GCC 2.8.1, `-mfp32`): its three
header commands written through the cursor were 5566, through `dl` 5256, each in a block of its own 4441; and every
`dl = gfx++` command of its switch in a block too 4241 (the judge's rows: the header's `move $a3, $s3; addiu $s3, 8`
pairs and the arms' `move $a1, $s3`). That the block scope works through the allocator's priorities is a hypothesis;
the judge decides each child.

Children (`gbi_block_cursor`): every site rewritten; only the runs through the cursor itself; only the shared-pointer
commands. A site is (a) `P->x = A; P->y = B; P++;` on consecutive lines, `P` a pointer declared `T *P` (a parameter
or a local), or (b) `D = P++;` with the simple statements after it on the same indentation up to the last that names
`D`, when `D` is a local `T *D` that the rest of the function only assigns again before reading.
"""
import re

from .csource import _blank, find

FAMILY = 'gbi_block_cursor'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    out = []
    for kinds in (('run', 'copy'), ('run',), ('copy',)):
        text = rewrite(source, name, kinds)
        if text and text != source and text not in out:
            out.append(text)
    return [(FAMILY, text) for text in out]


def _pointer_types(clean, start, opening, end):
    types = {}
    head = clean[start:opening]
    params = head[head.find('(') + 1:head.rfind(')')]
    for part in params.split(','):
        hit = re.fullmatch(rf'\s*(?:const\s+)?({IDENT})\s*\*\s*({IDENT})\s*', part)
        if hit:
            types[hit[2]] = hit[1]
    for hit in re.finditer(rf'(?m)^[ \t]*(?:const\s+)?({IDENT})\s*\*\s*({IDENT})\s*;', clean[opening:end]):
        if hit[1] not in ('return', 'goto', 'else'):
            types.setdefault(hit[2], hit[1])
    return types


def _names(text, var):
    return re.search(rf'(?<![\w.>]){re.escape(var)}\b', text) is not None


def _next_use_is_assignment(clean, at, end, var):
    """Whether `var` is not read after `at` before it is assigned again (or the function ends)."""
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[at:end]):
        rest = clean[at + hit.end():end]
        return bool(re.match(r'\s*=(?!=)', rest))
    return True


def rewrite(source, name, kinds=('run', 'copy')):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return None
    types = _pointer_types(clean, start, opening, end)
    lines = source[opening:end].split('\n')
    plain = clean[opening:end].split('\n')
    offsets, at = [], opening
    for line in lines:
        offsets.append(at)
        at += len(line) + 1
    edits = []
    i = 0
    while i < len(lines):
        line = plain[i]
        run = re.fullmatch(rf'([ \t]*)({IDENT})->({IDENT})\s*=\s*[^;{{}}]*;\s*', line)
        copy = re.fullmatch(rf'([ \t]*)({IDENT})\s*=\s*({IDENT})\+\+\s*;\s*', line)
        if 'run' in kinds and run and run[2] in types and i + 2 < len(lines):
            ind, ptr = run[1], run[2]
            second = re.fullmatch(rf'{re.escape(ind)}{re.escape(ptr)}->({IDENT})\s*=\s*[^;{{}}]*;\s*', plain[i + 1])
            step = re.fullmatch(rf'{re.escape(ind)}{re.escape(ptr)}(?:\+\+|\s*\+=\s*1)\s*;\s*', plain[i + 2])
            if second and step and not any(_names(plain[k].split('=', 1)[1], ptr) for k in (i, i + 1)):
                body = [ind + '    ' + re.sub(rf'^{re.escape(ptr)}->', '_g->', lines[k][len(ind):]) for k in (i, i + 1)]
                edits.append((i, i + 3, [ind + '{', f'{ind}    {types[ptr]} *_g = {ptr}++;'] + body + [ind + '}']))
                i += 3
                continue
        if 'copy' in kinds and copy and copy[2] in types and copy[3] in types and copy[2] != copy[3]:
            ind, dst, cur = copy[1], copy[2], copy[3]
            last, j = None, i + 1
            while j < len(lines):
                body = plain[j]
                if not body.strip():
                    j += 1
                    continue
                if not body.startswith(ind) or body[len(ind):len(ind) + 1] in (' ', '\t', '}'):
                    break
                text = body[len(ind):]
                if re.match(r'(?:break|case\b|default\b|return\b|goto\b|' + re.escape(dst) + r'\s*=)', text) \
                        or not re.fullmatch(r'[^{};]*;\s*', text) or re.search(rf'\b{re.escape(cur)}\b', text) \
                        and _names(text, dst):
                    break
                if _names(text, dst):
                    if not re.fullmatch(rf'\s*{re.escape(dst)}->{IDENT}\s*=[^;]*;\s*', text) \
                            or _names(text.split('=', 1)[1], dst):
                        break
                    last = j
                j += 1
            if last is not None and _next_use_is_assignment(clean, offsets[last] + len(plain[last]), end, dst):
                body = []
                for k in range(i + 1, last + 1):
                    text = lines[k].replace(f'{dst}->', '_g->')
                    body.append(('    ' + text) if text.strip() else text)
                edits.append((i, last + 1, [ind + '{', f'{ind}    {types[dst]} *_g = {cur}++;'] + body + [ind + '}']))
                i = last + 1
                continue
        i += 1
    if not edits:
        return None
    for a, b, new in reversed(edits):
        lines[a:b] = new
    return source[:opening] + '\n'.join(lines) + source[end:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
