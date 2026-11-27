"""A loaded value stored after a run of constant stores, moved up into the run.

m2c emits a record's initialisation in the order its own pass met the instructions, so a store whose value is loaded
(`c->serial = parent->serial + 0x21;`, or m2c's staged `t = *LOAD; sum = t + 0x21; STORE = sum;`) often ends up below
a run of constant stores, when the original computed it first. The place matters twice: the load's register lives across
the constants after it, so the constants take other registers and the record pointer is allocated elsewhere, and the
load sits where the target has it. A 59-instruction N64 effect spawner (SN GCC 2.8.1 `-G0 -mips3 -O2`) had that
store below seven constant stores of the new record: moved above them, 15 -> 0 on its chain (295 -> 0 on a hand-written
form of it). `statement_slide` reaches four statements and only `M2C_FIELD` or record-cast cells, so it never offered
a move of seven places over `->` or expanded cast stores.

A child moves the group (zero to two local assignments, then the store that uses them) above one of the constant stores
that precede it: the head of that run first, then each later place. A group is offered only when its statements make no
call and read memory, and no passed store is written the same way as a cell the group reads or writes. That is not a
proof the two pointers cannot overlap: the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'late_load_store_hoist'
FAMILIES = (FAMILY,)
LIMIT = 24
PLACES = 12  # places offered per group, from the head of its run of constant stores

_NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?f?)[uUlL]*'
_CONSTANT = re.compile(rf'^(?P<lhs>[^=;{{}}]+?)\s*=\s*(?:\(\s*\w+\s*\**\)\s*)*{_NUMBER}\s*;$')
_ASSIGN = re.compile(r'^(?P<lhs>[^=;{}]+?)\s*=(?!=)\s*(?P<rhs>[^;{}]+)$')
_LOCAL = re.compile(rf'^{IDENT}$')
_MEMORY = re.compile(r'M2C_FIELD\(|->|\(\s*\*\s*\(|\*\s*\(\s*\(?\s*[A-Za-z_]\w*\s*\*')
_CALL = re.compile(rf'\b(?!(?:sizeof|M2C_FIELD)\b){IDENT}\s*\(')
_CAST_CALL = re.compile(r'\(\s*(?:[su](?:8|16|32)|f32|char|short|int|long|void)\s*\**\s*\)')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _is_cell(lhs):
    lhs = lhs.strip()
    return '->' in lhs or lhs.startswith(('*', '(*', '( *', 'M2C_FIELD('))


def _calls(text):
    return bool(_CALL.search(_CAST_CALL.sub(' ', text)))


def _assignments(line):
    """[(lhs, rhs)] of a line made only of plain assignments, or None."""
    text = line.strip()
    if not text.endswith(';') or '{' in text or '}' in text or _calls(text):
        return None
    out = []
    for piece in text[:-1].split(';'):
        found = _ASSIGN.match(piece.strip())
        if not found or re.search(r'(?:[-+*/%&|^<>])$', found['lhs']):
            return None
        out.append((found['lhs'].strip(), found['rhs'].strip()))
    return out


def _constant_store(line):
    found = _CONSTANT.match(line.strip())
    return found['lhs'].strip() if found and _is_cell(found['lhs']) else None


def _group(lines, at):
    """(first line, cells written or read) of the group whose store is line `at`, or None."""
    store = _assignments(lines[at])
    if not store or len(store) != 1 or not _is_cell(store[0][0]) or _constant_store(lines[at]):
        return None
    lhs, rhs = store[0]
    first, reads = at, [rhs]
    needed = set(re.findall(IDENT, rhs))
    while at - first < 2 and first > 0:
        before = _assignments(lines[first - 1])
        if not before or not all(_LOCAL.match(left) for left, _ in before) or not needed & {left for left, _ in before}:
            break
        first -= 1
        for _, right in before:
            reads.append(right)
            needed |= set(re.findall(IDENT, right))
    if not any(_MEMORY.search(text) for text in reads):
        return None
    return first, lhs, reads


def variants(source, name):
    """Children: each late loaded-value store moved above the constant stores that precede it."""
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end].split('\n')
    original = source[part.opening:part.end].split('\n')
    if len(body) != len(original):
        return []
    out = []
    for at in range(1, len(body)):
        found = _group(body, at)
        if not found:
            continue
        first, lhs, reads = found
        read_text = _squash(' '.join(reads))
        places = []
        head = first - 1
        while head >= 0:
            cell = _constant_store(body[head])
            if cell is None or _squash(cell) == _squash(lhs) or _squash(cell) in read_text:
                break
            places.append(head)
            head -= 1
        if len(places) < 2:
            continue
        for place in places[::-1][:PLACES]:
            moved = original[:place] + original[first:at + 1] + original[place:first] + original[at + 1:]
            child = source[:part.opening] + '\n'.join(moved) + source[part.end:]
            out.append((FAMILY, child))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
