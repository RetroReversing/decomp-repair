"""A stack block filled for a call, rebuilt whole: one array, its constant stores in slot order, as one child.

m2c splits a configuration block that a function fills on its stack and passes by address into several locals
(`s32 sp10[2]; M2C_UNK *sp18; s32 sp1C[13];`), keeps the stores in the order the scheduler emitted them, sometimes
inside a `do { } while (0);`, and can leave a global copied from a temporary before that temporary is set. An N64
audio start-up function (SN GCC 2.7.2, `-O2`, 52 instructions) stood at 655 like that. Making it one array alone
gave 393, moving the early read 633, dropping the fence 273: the library had each step, but they only gave an exact
match together with the stores written in slot order, so a greedy search stopped (232 after 110 judged).

This module offers them together. The array comes from `stack_locals_one_array` (or is already one), grown up to the
lowest saved register's slot. The statements between the first block store and the call that takes the block are
rewritten: constant stores ascending by slot; the other statements (the computation of a slot and the globals beside
it) kept together where their slot is, a temporary's definition before its reads; fences removed. Where two
neighbouring non-zero constants are stored by the target the other way round, that order is offered too (constants
that share one register come out in source order), and `g = t` after `t = e` is also offered as `g = (t = e)`.
At most eight children. A candidate for the judge, never a verdict.
"""
import re

from . import stack_locals_one_array
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'frame_block_init_order'
FAMILIES = (FAMILY,)
LIMIT = 8

BUFFER = re.compile(r'(?m)^[ \t]*[su]32[ \t]+(?P<name>sp(?P<off>[0-9A-Fa-f]+))\[(?P<count>\d+)\][ \t]*;')
SAVE = re.compile(r'\bsw\s+\$?(?:ra|s[0-7]|fp)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\(\s*\$?sp\s*\)')
STORE = re.compile(r'\bsw\s+\$?\w+\s*,\s*(0x[0-9A-Fa-f]+|\d+)\(\s*\$?sp\s*\)')
FENCE = re.compile(r'\bdo\s*\{|\}\s*while\s*\(\s*0\s*\)\s*;')
ASSIGN = re.compile(r'(?P<lhs>[A-Za-z_]\w*(?:\[\d+\])?)\s*=(?!=)\s*(?P<rhs>.+)', re.S)
CAST = r'(?:\(\s*[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\**\s*\)\s*)*'
CONSTANT = re.compile(CAST + r'(?:\(\s*&\s*\w+\s*\)|&\s*\w+|-?(?:0x[0-9A-Fa-f]+|\d+)[uUlL]*)')
CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')
IDENT = re.compile(r'(?<![\w.>])[A-Za-z_]\w*')


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, opening, end) if end else None


def _region(clean, opening, end, buf):
    """(start, stop) of the lines from the first store into `buf` up to the call that receives it."""
    first = re.compile(r'(?m)^[ \t]*(?:do\s*\{\s*)?' + buf + r'\[\d+\]\s*=(?!=)').search(clean, opening, end)
    if not first:
        return None
    call = re.compile(r'(?m)^[ \t]*[^;\n{}]*\b[A-Za-z_]\w*\s*\(\s*(?:[^;{}()]*,\s*)?' + buf + r'\s*[,)]').search(
        clean, first.start(), end)
    return (first.start(), call.start()) if call else None


def _statements(text):
    """The region as (lhs, rhs) assignments once its one-shot fences are gone; None for anything else."""
    text = FENCE.sub(' ', text)
    if '{' in text or '}' in text:
        return None
    parts = [part.strip() for part in text.split(';')]
    if parts.pop():
        return None
    result = []
    for part in parts:
        hit = ASSIGN.fullmatch(part)
        if not hit or CALL.search(hit['rhs']) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', hit['rhs']):
            return None
        result.append((hit['lhs'], ' '.join(hit['rhs'].split())))
    return result


def _ordered(group, local_names):
    """The computed statements with each local's one definition before the statements that read it."""
    defined = {}
    for i, (lhs, _) in enumerate(group):
        if lhs in local_names:
            if lhs in defined:
                return None
            defined[lhs] = i
    order, seen, busy = [], set(), set()

    def place(i):
        if i in seen:
            return True
        if i in busy:
            return False
        busy.add(i)
        reads = set(IDENT.findall(group[i][1]))
        for other, (lhs, _) in enumerate(group):
            needed = lhs in reads and (lhs in local_names or other < i)
            if needed and other != i and not place(other):
                return False
        if group[i][0] in local_names and group[i][0] in reads:
            return False
        seen.add(i)
        order.append(group[i])
        return True

    return order if all(place(i) for i in range(len(group))) else None


def _chained(group, local_names):
    """`t = e; g = t;` written `g = (t = e);`."""
    for i in range(len(group) - 1):
        (temp, value), (target, copy) = group[i], group[i + 1]
        if temp in local_names and copy == temp and target not in local_names and '[' not in target:
            return group[:i] + [(target, f'({temp} = {value})')] + group[i + 2:]
    return None


def _rebuilt(source, name, buf, base, asm):
    parsed = _body(source, name)
    if not parsed:
        return []
    clean, opening, end = parsed
    declared = next((m for m in BUFFER.finditer(clean, opening, end) if m['name'] == buf), None)
    region = _region(clean, opening, end, buf)
    if not declared or not region:
        return []
    statements = _statements(clean[region[0]:region[1]])
    if not statements:
        return []
    constants, group, slots = {}, [], []
    for lhs, rhs in statements:
        slot = re.fullmatch(buf + r'\[(\d+)\]', lhs)
        if slot and int(slot[1]) in slots:
            return []
        if slot:
            slots.append(int(slot[1]))
        if slot and CONSTANT.fullmatch(rhs):
            constants[int(slot[1])] = rhs
        elif re.search(r'(?<![\w.>])' + buf + r'\b', rhs):
            return []
        else:
            group.append((lhs, rhs))
    if len(constants) < 4:
        return []
    local_names = set(re.findall(r'(?m)^[ \t]*[A-Za-z_][\w ]*?[ \t*]+([A-Za-z_]\w*)\s*;', clean[opening:region[0]]))
    group = _ordered(group, local_names)
    if group is None:
        return []
    computed = [int(hit[1]) for hit in (re.fullmatch(buf + r'\[(\d+)\]', lhs) for lhs, _ in group) if hit]
    if group and not computed:
        return []
    anchor = min(computed) if computed else None

    ascending = sorted(constants) + ([anchor] if anchor is not None else [])
    ascending.sort()
    seen = {}
    for position, hit in enumerate(STORE.finditer(asm)):
        seen.setdefault(int(hit[1], 0), position)
    turned = list(ascending)
    for i in range(len(turned) - 1):
        low, high = turned[i], turned[i + 1]
        pair = (constants.get(low), constants.get(high))
        if None in pair or '0' in pair:
            continue
        where = (seen.get(base + 4 * low), seen.get(base + 4 * high))
        if None not in where and where[1] < where[0]:
            turned[i], turned[i + 1] = high, low

    size = int(declared['count'])
    saves = [int(hit[1], 0) for hit in SAVE.finditer(asm)]
    room = (min(saves) - base) // 4 if saves else 0
    sizes = [room] if size < room <= size + 4 else [size]

    indent = re.match(r'[ \t]*', clean[region[0]:])[0]
    chained = _chained(group, local_names)
    out = []
    for order in (turned, ascending):
        for middle in (chained, group):
            if middle is None:
                continue
            lines = []
            for slot in order:
                if slot == anchor:
                    lines += [f'{lhs} = {rhs};' for lhs, rhs in middle]
                else:
                    lines.append(f'{buf}[{slot}] = {constants[slot]};')
            block = ''.join(f'{indent}{line}\n' for line in lines)
            for count in sizes:
                text = source[:region[0]] + block + source[region[1]:]
                text = text[:declared.start('count')] + str(count) + text[declared.end('count'):]
                if text != source and text not in out:
                    out.append(text)
    return out


def variants(source, name, asm):
    if not asm or not _body(source, name):
        return []
    out = []
    merged = [text for _, text in stack_locals_one_array.variants(source, name)]
    for candidate in merged[:1] + [source]:
        parsed = _body(candidate, name)
        clean, opening, end = parsed
        for hit in BUFFER.finditer(clean, opening, end):
            for text in _rebuilt(candidate, name, hit['name'], int(hit['off'], 16), asm):
                if text != source and text not in out:
                    out.append(text)
        if out:
            break
    return [(FAMILY, text) for text in out[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm')}
