"""A member slot reached through the same `*(T *)(base + K)` more than once in a block, held in a pointer local.

m2c writes every access to a record's member as `*((void **) (((char *) base) + 0x418))`. In a loop body the target often
shows the slot's address once, in a register of its own that the store and a later argument read both use (`addiu $s4,
$s1, 0x418` beside `lw $v0, 0x418($s1)` and a later `lw $a0, 0($a0)`), the way a developer holds `T **slot = &obj->m[i]`:

    do {
        if (*(void **)(base + 0x418) == NULL) {
            *(void **)(base + 0x418) = make();          ->   void **slot = (void **)(base + 0x418);
            if (...) use(*(void **)(base + 0x418), ...);      *slot = make();  if (...) use(*slot, ...);

Written as the pointer local, in the block that holds the second and later accesses (the test before the block stays as
it was), loop.c reduces the address once per iteration from the counter's own giv instead of making the slot's address
the induction variable (a 1133-instruction effect spawner, KMC GCC 2.7.2: 7905 -> 6798 for this edit alone). The local is
set at the head of the innermost block that holds two or more accesses, and only when the base is not assigned in it;
blocks inside a loop come first (loop.c is what the edit changes).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'member_slot_pointer_local'
FAMILIES = (FAMILY,)
LIMIT = 6

ACCESS = re.compile(r'\*\s*\(\(\s*([A-Za-z_][\w \t]*?\s*\*+)\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*([A-Za-z_]\w*)\s*\)\s*'
                    r'\+\s*(0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*\)')


def _blocks(clean, start, end):
    """(open, close) of every `{ }` pair inside clean[start:end], innermost last in each nest."""
    stack, found = [], []
    for position in range(start, end):
        ch = clean[position]
        if ch == '{':
            stack.append(position)
        elif ch == '}' and stack:
            found.append((stack.pop(), position))
    return found


def _is_loop_body(clean, opening):
    head = clean[:opening].rstrip()
    return head.endswith('do') or (head.endswith(')') and bool(re.search(r'\b(?:for|while)\s*\([^{};]*\)$', head)))


def _assigned(text, base):
    name = re.escape(base)
    return bool(re.search(r'(?<![\w.>])' + name + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + name + r'\b|\b' +
                          name + r'\s*(?:\+\+|--)|&\s*' + name + r'\b', text))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    blocks = [block for block in _blocks(clean, opening + 1, end - 1)]
    found = []
    for start, stop in blocks:
        inside = clean[start + 1:stop]
        # the accesses of this block that no inner block holds two of already: counted for the block as a whole
        counts = {}
        for hit in ACCESS.finditer(inside):
            key = (re.sub(r'\s+', ' ', hit[1]).strip(), hit[2], int(hit[3], 0))
            counts.setdefault(key, []).append(hit)
        for key, hits in counts.items():
            if len(hits) < 2 or _assigned(inside, key[1]):
                continue
            inner = [(a, b) for a, b in blocks if start < a and b < stop and
                     len([h for h in hits if a < start + 1 + h.start() < b]) == len(hits)]
            if inner:
                continue  # an inner block holds all of them: it is the one to take the local
            in_loop = any(a <= start and stop <= b and _is_loop_body(clean, a) for a, b in blocks)
            found.append((not in_loop, -len(hits), start, stop, key, hits))
    result = []
    for _, _, start, stop, key, hits in sorted(found, key=lambda item: item[:3]):
        pointer_type, base, offset = key
        local = f'{base}_slot_{offset:x}'
        if re.search(r'\b' + re.escape(local) + r'\b', source):
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0] + '  '
        text = source[start + 1:stop]
        shifted = [(h.start(), h.end()) for h in hits]
        for a, b in reversed(shifted):
            text = text[:a] + '(*' + local + ')' + text[b:]
        declaration = f'\n{indent}{pointer_type} {local} = ({pointer_type}) (((char *) {base}) + {hex(offset)});'
        result.append((FAMILY, source[:start + 1] + declaration + text + source[stop:]))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
