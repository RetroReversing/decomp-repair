"""An argument the target passes from a saved register that holds a symbol's address, added to the call.

A caller that keeps `&D` in `$s1` for later calls passes it on with a plain `move $a1, $s1` before a call that takes it,
so the C has nothing m2c can see: `func(D_8011F3AC);` where the game called `func(D_8011F3AC, D_8011F0E0)`. An N64
function was 97.3% so and exact with the argument added. The target says which: the argument registers past the call's
count that are copied from a saved register set from `%lo(SYMBOL)`. Offered for callees declared without parameters,
pairing the C's calls with the target's `jal`s to the same function in order; the symbol is written as the C writes it
elsewhere (`D` for an array it passes bare, `&D` otherwise).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'saved_register_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
INSN = re.compile(r'^\s*(?:/\*.*?\*/\s*)?(?P<op>[a-z0-9.]+)\s*(?P<ops>.*?)\s*$')


def _instructions(asm):
    for line in (asm or '').splitlines():
        m = INSN.match(line)
        if m and not line.strip().startswith(('glabel', '.', '#')) and not line.rstrip().endswith(':'):
            op, ops = m['op'], [o.strip() for o in m['ops'].split(',')] if m['ops'] else []
            # (`move` is written `addu rd, rs, $zero` by these assemblers, `or` by others)
            if op in ('addu', 'daddu', 'or') and len(ops) == 3 and ops[2] == '$zero':
                op, ops = 'move', ops[:2]
            yield op, ops


def passed(asm):
    """{callee: [ {arg index: symbol}, ... ]} for each `jal`, in order: arguments copied from a saved register that
    holds a symbol's address."""
    holds, found, setting = {}, {}, {}
    insns = list(_instructions(asm))
    for i, (op, ops) in enumerate(insns):
        if op == 'addiu' and len(ops) == 3 and ops[0].startswith('$s') and ops[0] == ops[1]:
            lo = re.match(r'%lo\((' + IDENT + r')\)', ops[2])
            if lo:
                holds[ops[0]] = lo[1]
        elif op in ('move', 'or', 'addu') and ops and ops[0].startswith('$s'):
            holds.pop(ops[0], None)
        if op == 'move' and len(ops) == 2 and re.fullmatch(r'\$a[0-3]', ops[0]) and ops[1] in holds:
            setting[int(ops[0][2])] = holds[ops[1]]
        elif ops and re.fullmatch(r'\$a[0-3]', ops[0]):
            setting.pop(int(ops[0][2]), None)
        if op == 'jal' and ops:
            # (the delay slot belongs to the call)
            if i + 1 < len(insns):
                d_op, d_ops = insns[i + 1]
                if d_op == 'move' and len(d_ops) == 2 and re.fullmatch(r'\$a[0-3]', d_ops[0]) and d_ops[1] in holds:
                    setting[int(d_ops[0][2])] = holds[d_ops[1]]
            found.setdefault(ops[0], []).append(dict(setting))
            setting = {}
        elif op in ('jalr', 'jr', 'j') or op.startswith('b'):
            setting = {}
    return found


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    unprototyped = set(re.findall(r'(?m)^[ \t]*(?:extern\s+)?[\w ]+?[\s*]+(' + IDENT + r')\s*\(\s*\)\s*;', outside))
    targets = passed(asm)
    body = clean[opening:end]
    calls = {}
    for m in re.finditer(r'\b(' + IDENT + r')\s*\(', body):
        if m[1] in unprototyped:
            calls.setdefault(m[1], []).append(m)
    edits = []
    for callee, sites in calls.items():
        seen = targets.get(callee, [])
        if len(seen) != len(sites):
            continue
        for site, regs in zip(sites, seen):
            paren = opening + site.end() - 1
            closing = close(clean, paren)
            inside = clean[paren + 1:closing - 1].strip()
            count = len([a for a in _split(inside)]) if inside else 0
            extra = [regs[k] for k in sorted(regs) if k >= count]
            if not extra or sorted(k for k in regs if k >= count) != list(range(count, count + len(extra))):
                continue
            words = []
            for symbol in extra:
                bare = re.search(r'[(,]\s*' + symbol + r'\s*[,)]', body)
                words.append(symbol if bare else '&' + symbol)
            edits.append((closing - 1, (', ' if count else '') + ', '.join(words)))
    if not edits:
        return []
    text = source
    for at, insert in sorted(edits, reverse=True):
        text = text[:at] + insert + text[at:]
    return [(FAMILY, text)]


def _split(text):
    parts, depth, cur = [], 0, ''
    for ch in text:
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ''
            continue
        depth += (ch in '([{') - (ch in ')]}')
        cur += ch
    return parts + [cur]
