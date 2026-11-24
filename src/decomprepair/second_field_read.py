"""A field read once into a local and used twice, read again (a second local) after an intervening store.

The shape (SN GCC 2.8.1, `-G0 -mips3 -O2`): m2c reads a record's field once, because the game's code did, and uses the
value twice, once as it is and once in arithmetic:

    a = F(0x7C);  t = F(0x80);  F(0x7C) = a + 1;  F(0x64) = t;  F(0x80) = t - 5;

The original read the field twice, the second time after a store to a neighbouring field, and used each read once:

    a = F(0x7C);  t = F(0x80);  F(0x7C) = a + 1;  u = F(0x80);  u -= 5;  F(0x64) = t;  F(0x80) = u;

GCC 2.8's reload_cse (the load of an address a register already holds becomes a copy) turns the second read into a
`move`, so the target has `lw $a0, 0x80(base)` followed by `move $v1, $a0`, where the single read has the plain `lw`
and two uses of one register. The copy is a register of its own, which is what changes the allocation of everything
after it.

The gate is that evidence: the target loads a field and, within three instructions, copies the register it loaded
(`move`, `addu rd, rs, $zero`, `or`, `mov.s`), and the field's offset is the one the local is read from. With no assembly
nothing is proposed.

`variants` finds, in one block, `L = F(base, T, X);` for a local `L` of the function, then the first store
`F(base, T2, Y) = value;` to a different, non-overlapping field of the same base, with only plain statements between
(assignments to locals, stores to non-overlapping fields of that base: nothing that could change field X) and `L` not
named until after that store, and then two to four later plain statements that read `L` (no write to it, no mention of it
elsewhere in the function). One child per later use `U` (at most MAX_USES): a new local `L_2` declared with `L`'s type,
`L_2 = F(base, T, X);` written right after the intervening store (`second_field_read`), or right before `U` when more
statements sit between (`second_field_read_late`), and `U` reading `L_2`. At most LIMIT children; the first use
whose arithmetic is a store back to the field is the likeliest, and each is judged anyway.

Faithful: the new read is of a field nothing has changed since the first, so both locals hold the same value; the value
is read the same number of times, the program gets one more load it can reuse. This module reads text only and never
compiles or judges."""
import re

from .hand_found_support import (
    IDENT,
    LOADS,
    blocks,
    calls_in,
    copy_source,
    declare,
    declaring,
    fields,
    fresh,
    instructions,
    local_type,
    memory,
    mentions_of,
    simple,
    stmts,
    store_target,
    writes,
)
from .integer_repair_support import edit, view

FAMILY = 'second_field_read'
LATE_FAMILY = 'second_field_read_late'
FAMILIES = (FAMILY, LATE_FAMILY)
LIMIT = 6
MAX_USES = 3
WINDOW = 3  # (instructions after the load that may hold its copy)


def evidence(asm):
    """{offset} of the fields the target loads and copies at once: `lw $a0, 0x80($s0)` then `move $v1, $a0`."""
    ops = instructions(asm)
    found = set()
    for index, (op, args) in enumerate(ops):
        if op not in LOADS or len(args) != 2 or not memory(args[1]):
            continue
        offset = memory(args[1])[0]
        for later, later_args in ops[index + 1:index + 1 + WINDOW]:
            copy = copy_source(later, later_args)
            if copy and copy[1] == args[0] and copy[0] != args[0]:
                found.add(offset)
                break
            if later_args and later_args[0] == args[0]:
                break  # (the loaded register was overwritten first)
    return found


def _store_lvalue(text):
    """The field a plain store statement writes, None for a store to a plain name; False when it is no plain store."""
    if not simple(text) or calls_in(text):
        return False
    stored = store_target(text)
    if not stored:
        return False
    lvalue = stored[0]
    if re.fullmatch(IDENT, lvalue):
        return None  # (a local or a global scalar named by itself: not the record's field)
    written = fields(lvalue)
    return written[0] if written and written[0].start == 0 and written[0].end == len(lvalue.rstrip()) else False


def _passes(text, base, field):
    """True when a plain statement between the first read and the second cannot change the field."""
    stored = _store_lvalue(text)
    return stored is None or (stored is not False and stored.base == base and not stored.overlaps(field))


def variants(source, name, header='', arch='mips', asm=''):
    if arch != 'mips':
        return []
    wanted = evidence(asm)
    part = view(source, name) if wanted else None
    if not part or not part.body.strip():
        return []
    clean = part.clean
    taken = set(re.findall(IDENT, source)) | set(re.findall(IDENT, header or ''))
    children = []
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        for index, (start, end) in enumerate(spans):
            read = re.fullmatch(rf'(?P<local>{IDENT})\s*=\s*(?P<field>M2C_FIELD\(.*\))\s*;', clean[start:end], re.S)
            if not read:
                continue
            local = read['local']
            found = fields(clean, start, end)
            if len(found) != 1 or found[0].end != start + read.end('field') or found[0].offset not in wanted:
                continue
            field = found[0]
            kind = local_type(part, local)
            if not kind or re.search(r'[\[\]]', kind):
                continue
            if len(mentions_of(clean[part.opening + 1:start], local)) != 1:
                continue  # (the declaration only: no earlier use, no earlier branch)
            everywhere = mentions_of(clean[start:part.end - 1], local)
            children += _children(source, part, spans, index, local, field, clean[start:end], kind, everywhere, taken)
    return list(dict.fromkeys(children))[:LIMIT]


def _children(source, part, spans, index, local, field, read_text, kind, everywhere, taken):
    clean = part.clean

    def text_of(at):
        return clean[spans[at][0]:spans[at][1]]

    store = None
    for at in range(index + 1, len(spans)):
        if mentions_of(text_of(at), local) or not _passes(text_of(at), field.base, field):
            return []
        if _store_lvalue(text_of(at)):
            store = at  # (the first store to another field of the record)
            break
    if store is None:
        return []
    uses = [at for at in range(store + 1, len(spans)) if mentions_of(text_of(at), local)]
    if not 2 <= len(uses) <= 4:
        return []
    if len(everywhere) != 1 + sum(len(mentions_of(text_of(at), local)) for at in uses):
        return []  # (named somewhere else too: a loop, a branch, the rest of the function)
    if any(not simple(text_of(at)) or writes(text_of(at), local) for at in uses):
        return []
    new = fresh(local, taken, '2')
    declaration = declare(source, part, [declaring(kind, new)])
    if not declaration:
        return []
    reread = re.sub(rf'^{re.escape(local)}\b', new, read_text.strip())
    out, late = [], False
    for at in uses[:MAX_USES]:
        if any(not _passes(text_of(b), field.base, field) for b in range(store + 1, at)):
            break  # (a statement before this use may change the field: this and every later use would read it stale)
        a, b = spans[at]
        replaced = re.sub(rf'(?<![\w.>]){re.escape(local)}\b', new, source[a:b])
        after = spans[store][1]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, spans[store][0]) + 1:])[0]
        out.append((FAMILY, edit(source, [declaration, (after, after, f'\n{indent}{reread}'), (a, b, replaced)])))
        if at > store + 1 and not late:
            late = True
            indent_use = re.match(r'[ \t]*', source[source.rfind('\n', 0, a) + 1:])[0]
            out.append((LATE_FAMILY, edit(source, [declaration, (a, b, f'{reread}\n{indent_use}{replaced}')])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm'),
          'order': 66, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
