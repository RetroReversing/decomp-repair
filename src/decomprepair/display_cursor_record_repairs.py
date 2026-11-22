"""A display-list cursor the game advanced one command at a time: a record pointer, each command's words its members.

Game code that builds a graphics display list writes `g = cursor++; g->w0 = A; g->w1 = B;` for every command, where
`cursor` is a global pointer to an eight-byte record. m2c reads such a function back as one read of the global, the
raw stores of several commands through the local, and then every `cursor = base + 8 * n` in a row. gcc 2.7.2 keeps
the original's shape only when both halves are right, and a search that fixes one half sees nothing:

- a store through a structure member never clobbers a scalar global in alias.c's view (MEM_IN_STRUCT_P), so the
  cursor's value stays known across the words the command writes and the next `cursor++` costs no reload; a raw
  `*(s32 *)(p + off)` store is not "in struct" and gcc reloads, so the draft (and `volatile_reload`, which exists
  for exactly this symptom) declared the pointer `volatile` to get the reloads back and kept a score near 1800;
- each advance has to sit between its command's words and the next command's, or cse treats the earlier stores to
  the global as dead and deletes them (the target keeps all five of its advances, one `lui $at; sw` each).

On an N64 function of 318 instructions (KMC gcc 2.7.2) the draft with a `void * volatile` cursor judged 1825; with a
`CursorRecord *` cursor, the words as members and each advance first in its command (the post-increment's order),
and three smaller repairs in the same function, it was byte-identical. This family writes the cursor as a record
pointer (no `volatile`), the words as `((CursorRecord *) p)[command].wN`, and moves every `cursor = p + K` that
closes a command to just before that command's first word (`display_cursor_record`) or just after its last one
(`display_cursor_record_after`). It needs a plain pointer global (`void`, byte or word base), a local read from it,
and two or more advances whose offsets are multiples of eight; it leaves everything else alone. The compiler and
judge decide whether the result helps.

A word-typed cursor (`s32 * volatile cursor`, the draft of an 842-instruction N64 lit-actor drawer, saved best 8827
after the volatile was dropped by hand and 7722 / 6442 once its first two commands were members) counts its advances
in words, `cursor = p + 2` for eight bytes, and the draft writes the first word of a command through the app's
one-member record (`((__repair_field_0 *) p)->value = A;`). Both were invisible to the first version: the advance
steps are scaled by the pointee's size (`s32`/`u32`/`int` 4, `s8`/`u8`/`char`/`void` 1), and a store through a
one-member record whose typedef is in the source is a word store at the member's offset (the `pad[N]` before it).
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'display_cursor_record'
AFTER_FAMILY = 'display_cursor_record_after'
ORDERED_FAMILY = 'display_cursor_record_ordered'
FAMILIES = (FAMILY, AFTER_FAMILY, ORDERED_FAMILY)
LIMIT = 4
RECORD = 'CursorRecord'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'

POINTER = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>void|char|s8|u8|s32|u32|int|unsigned)\s*\*\s*(?:volatile\s+)?(?P<name>{IDENT})\s*;')
WORD_TYPES = {'s32', 'u32', 'int', 'unsigned'}
MEMBER = re.compile(rf'(?:\(\s*\(\s*(?P<t1>{IDENT})\s*\*\s*\)\s*(?P<p1>{IDENT})\s*\)\s*->|\(\s*\*\s*\(\s*\(\s*(?P<t2>{IDENT})\s*\*\s*\)\s*(?P<p2>{IDENT})\s*\)\s*\)\s*\.)\s*'
                    rf'(?P<m>{IDENT})\s*=(?!=)\s*(?P<v>[^;]+?)\s*;\Z')
RECORD_TYPEDEF = re.compile(rf'typedef\s+struct\s*\{{\s*(?:(?:unsigned\s+char|u8|char)\s+{IDENT}\s*\[\s*(?P<pad>{NUMBER})\s*\]\s*;\s*)?'
                            rf'(?:int|s32|u32|unsigned(?:\s+int)?)\s+(?P<member>{IDENT})\s*;\s*\}}\s*(?P<name>{IDENT})\s*;')
STORE = re.compile(rf'\*\s*\(\s*\(\s*(?:s32|u32)\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<p>{IDENT})\s*\)\s*'
                   rf'\+\s*(?P<off>{NUMBER})\s*\)\s*\)\s*=(?!=)\s*(?P<v>[^;]+?)\s*;\Z')
DERIVED = re.compile(rf'(?P<y>{IDENT})\s*=\s*(?P<x>{IDENT})\s*\+\s*(?P<k>{NUMBER})\s*;\Z')


def _statements(clean, start, end):
    """(start, end) of each `;`-ended statement in the body span; a brace or label ends a run and is not a statement."""
    out, begin = [], start
    for i in range(start, end):
        ch = clean[i]
        if ch in '{}':
            begin = i + 1
        elif ch == ';':
            if clean[begin:i + 1].strip():
                out.append((begin + len(clean[begin:i + 1]) - len(clean[begin:i + 1].lstrip()), i + 1))
            begin = i + 1
    return out


def _number(text):
    return int(text, 0)


def _store(text, records):
    """(pointer, byte offset, value text) of a word store through a raw cast or through a one-member record, else None."""
    if s := STORE.match(text):
        return s['p'], _number(s['off']), s['v']
    if (m := MEMBER.match(text)) is not None:
        kind, pointer = (m['t1'], m['p1']) if m['t1'] else (m['t2'], m['p2'])
        if kind in records and records[kind][0] == m['m']:
            return pointer, records[kind][1], m['v']
    return None


def _records(clean):
    """name -> (member, byte offset) of each one-member word record typedef in the source (`pad[N]` before the member)."""
    return {m['name']: (m['member'], _number(m['pad']) if m['pad'] else 0) for m in RECORD_TYPEDEF.finditer(clean)}


def _plan(clean, spans, cursor, scale=1, records=None, minimum=2, roots=None):
    """Per read of `cursor`: the stores through what was read, the advances back into the cursor and their commands.

    A later read starts its own group but earlier groups stay open: m2c's second command often stores through a
    pointer derived from the first read after a reload of the cursor.
    """
    records = records or {}
    read = re.compile(rf'(?P<x>{IDENT})\s*=\s*{re.escape(cursor)}\s*;\Z')
    write = re.compile(rf'{re.escape(cursor)}\s*=\s*(?P<p>{IDENT})\s*(?:\+\s*(?P<k>{NUMBER})\s*)?;\Z')
    groups = []
    for index, (a, b) in enumerate(spans):
        text = clean[a:b]
        if hit := read.match(text):
            groups.append({'root': hit['x'], 'base': {hit['x']: 0}, 'stores': [], 'advances': []})
            continue
        if (d := DERIVED.match(text)) and d['y'] != cursor:
            for group in groups:
                if d['x'] in group['base'] and d['y'] not in group['base']:
                    group['base'][d['y']] = group['base'][d['x']] + _number(d['k']) * scale
                    break
            continue
        if (s := _store(text, records)) is not None:
            pointer, offset, _ = s
            for group in groups:
                if pointer in group['base'] and offset % 4 == 0:
                    group['stores'].append((index, pointer, offset, group['base'][pointer] + offset))
                    break
            continue
        if w := write.match(text):
            for group in groups:
                if w['p'] in group['base']:
                    total = group['base'][w['p']] + _number(w['k'] or '0') * scale
                    if total % 8 == 0 and total > 0:
                        group['advances'].append((index, group['root'], total // 8))
                    break
    return [g for g in groups if len(g['advances']) >= minimum and g['stores'] and (roots is None or g['root'] in roots)]


def _rewrite(source, part, spans, groups, after, cursor, records=None, scale=1, ordered=False):
    """Edits that put the records in and each advance by its command's words; None when nothing moves.

    `ordered` also hands the group's store statements back in command order (each command's first word, then its
    second), in the statement slots the stores already occupy: m2c writes the second command's colour word before the
    first command's (the order of the loads it was scheduled in), and the original wrote each command whole."""
    clean = part.clean
    records = records or {}
    edits, moved = [], 0
    for group in groups:
        stores = list(group['stores'])
        slots = {index: index for index, *_ in stores}
        if ordered:
            positions = sorted(index for index, *_ in stores)
            if re.search(r'[{}]|\b(?:if|else|while|for|goto|return)\b|:', clean[spans[positions[0]][0]:spans[positions[-1]][1]]):
                continue  # the stores sit in different blocks: reordering them would move a store out of its branch
            by_offset = sorted(stores, key=lambda item: item[3])
            slots = {item[0]: positions[k] for k, item in enumerate(by_offset)}
            if all(old == new for old, new in slots.items()):
                continue
            moved += 1
        by_command = {}
        for index, pointer, off, absolute in stores:
            by_command.setdefault(absolute // 8, []).append(slots[index])
        for index, pointer, off, absolute in stores:
            a, b = spans[index]
            value = _store(clean[a:b], records)[2]
            start = clean.index(value, a)
            member = f'((({RECORD} *) {pointer})[{off // 8}].w{(off % 8) // 4})'
            c, d = spans[slots[index]]
            edits.append((c, d, f'{member[1:-1]} = {source[start:start + len(value)]};'))
        placed = set()
        for index, pointer, command in group['advances']:
            a, b = spans[index]
            stores = by_command.get(command - 1)
            if not stores or command in placed:
                continue
            placed.add(command)
            target = max(stores) if after else min(stores)
            if target == index:
                continue
            low, high = sorted((index, target))
            if re.search(r'[{}]|\b(?:if|else|while|for|goto|return)\b|:', clean[spans[low][0]:spans[high][1]]):
                continue  # an advance in another block than its command's words stays where it is
            # (written from the group's own read, which is defined before any of the command's words)
            text = f'{cursor} = {pointer} + {hex(command * 8 // scale)};'
            edits.append((a, b, ''))
            if after:
                edits.append((spans[target][1], spans[target][1], '\n    ' + text))
            else:
                edits.append((spans[target][0], spans[target][0], text + '\n    '))
            moved += 1
    return edits if moved else None


def variants(source, name, header='', minimum=2, roots=None):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(rf'\b{RECORD}\b', header + clean):
        return []
    spans = _statements(clean, part.opening + 1, part.end - 1)
    result = []
    records = _records(clean[:part.opening])
    for pointer in POINTER.finditer(clean[:part.opening]):
        cursor = pointer['name']
        scale = 4 if pointer['type'] in WORD_TYPES else 1
        groups = _plan(clean, spans, cursor, scale, records, minimum, roots)
        if not groups:
            continue
        for after, ordered, family in ((False, True, ORDERED_FAMILY), (False, False, FAMILY), (True, False, AFTER_FAMILY)):
            edits = _rewrite(source, part, spans, groups, after, cursor, records, scale, ordered)
            if not edits:
                continue
            typedef = f'typedef struct {{ s32 w0; s32 w1; }} {RECORD};\n'
            edits = [(pointer.start(), pointer.end(), f'{typedef}extern {RECORD} *{cursor};')] + edits
            try:
                result.append((family, edit(source, sorted(edits, key=lambda e: (e[0], e[1])))))
            except ValueError:
                continue
        if len(result) >= LIMIT:
            break
    return result
