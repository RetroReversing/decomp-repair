"""A stack array's address passed to calls inside a loop, named in a pointer local set before the loop with its siblings.

GCC 2.7.2's loop.c hoists a frame address (`addiu $t4, $sp, 0x168`) that calls in a loop take as an argument out of the
loop, and reload spills it to a slot of its own (`sw $t4, 0x224($sp)`, then `lw $a0, 0x224($sp)` at each call). m2c
writes those spilled invariants as pointer locals set before the loop (`sp21C = &sp158;`), but when one argument is
left as `&sp168` in the calls, the compiler keeps it as a fresh `addiu` per call: the target's slot and its loads are
missing, and every register and slot after it moves. Named in a local set beside the loop's other pointer locals, the
address is hoisted and spilled like its siblings.

A 1928-instruction collision sweep (KMC gcc 2.7.2): two byte-triangle loops each passed one array directly while the
target loaded it from a spill slot; named, 23701 -> 23173 -> 21398 (the second loop's only paying off once its frame
slots were right). That the original spelled it this way is one function; loop.c hoisting the address is the compiler's
behaviour, the source's spelling is a hypothesis.

Children: one per (loop, array) pair, and one naming at once every array whose calls pass, in that argument, what other
calls of the same callee pass as such a pointer local (the spilled-invariant signature).
"""
import re

from .csource import _blank, find

FAMILY = 'loop_address_argument_local'
COMBINED = 'loop_address_argument_local_all'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'


def _loops(clean, start, end):
    """(do-open, body-start, body-end) of each `do { ... } while` in [start, end)."""
    out = []
    for m in re.finditer(r'\bdo\s*\{', clean[start:end]):
        opening = start + m.end() - 1
        depth = 0
        for k in range(opening, end):
            if clean[k] == '{':
                depth += 1
            elif clean[k] == '}':
                depth -= 1
                if depth == 0:
                    out.append((start + m.start(), opening + 1, k))
                    break
    return out


def _pointer_setups(source, clean, do_at):
    """Where the new local's line goes: after the last `name = &X;` line of the simple assignments right before `do`, or
    at the head of that run when it has none; and the `do` line's start (for its indentation)."""
    line_start = source.rfind('\n', 0, do_at) + 1
    last = None
    k = line_start
    for _ in range(4):
        prev = source.rfind('\n', 0, k - 1) + 1
        line = clean[prev:k]
        if re.match(r'^[ \t]*' + I + r'\s*=\s*&\s*' + I + r'\s*;\s*$', line):
            last = k
            break
        if not re.match(r'^[ \t]*' + I + r'\s*=\s*[^;{}]*;\s*$', line):
            break
        k = prev
    return (last if last is not None else k), line_start


def _element_type(source, array):
    """`f32` for `#define sp168 stack_sp168[0]` with `f32 stack_sp168[3];`, or for `f32 sp168[3];`."""
    define = re.search(r'(?m)^#define\s+' + array + r'\s+(' + I + r')\s*\[', source)
    base = define.group(1) if define else array
    decl = re.search(r'(?m)^[ \t]*((?:unsigned\s+|signed\s+)?' + I + r')\s+' + base + r'\s*\[', source)
    return decl.group(1) if decl else 'void'


def _argument(array):
    """`&X` as a whole call argument, optionally cast and parenthesised."""
    return re.compile(r'(?<=[(,])(?P<pre>\s*)(?P<cast>\(\s*' + I + r'\s*\*\s*\)\s*)?(?:\(\s*&\s*' + array +
                      r'\s*\)|&\s*' + array + r'\b)(?=\s*[,)])')


def _call_slot(clean, at):
    """(callee, argument index) of the call whose argument list holds position `at`, or None."""
    depth = 0
    index = 0
    for k in range(at - 1, -1, -1):
        c = clean[k]
        if c == ')':
            depth += 1
        elif c == '(':
            if depth == 0:
                m = re.search(r'(' + I + r')\s*$', clean[:k])
                return (m.group(1), index) if m else None
            depth -= 1
        elif c == ',' and depth == 0:
            index += 1
        elif c in ';{}':
            return None
    return None


def _sibling_slots(clean, start, end):
    """(callee, index) pairs where some call passes a pointer local that is assigned `= &X;` (a spilled invariant)."""
    pointers = set(re.findall(r'\b(' + I + r')\s*=\s*&\s*' + I + r'\s*;', clean[start:end]))
    slots = set()
    for m in re.finditer(r'(?<=[(,])\s*(?:\(\s*' + I + r'\s*\*\s*\)\s*)?(' + I + r')(?=\s*[,)])', clean[start:end]):
        if m.group(1) in pointers:
            slot = _call_slot(clean, start + m.start(1))
            if slot:
                slots.add(slot)
    return slots


def _plan(source, name):
    span = find(source, name)
    if not span:
        return None, []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None, []
    plans = []
    siblings = _sibling_slots(clean, opening, span[1])
    for do_at, body_start, body_end in _loops(clean, opening, span[1]):
        setup_end, line_start = _pointer_setups(source, clean, do_at)
        body = clean[body_start:body_end]
        # Only the innermost loop owning the calls: skip a loop holding another `do`.
        if re.search(r'\bdo\s*\{', body):
            continue
        for array in sorted(set(re.findall(r'&\s*\(?\s*(' + I + r')\b', body))):
            hits = [m for m in _argument(array).finditer(body) if _call_slot(clean, body_start + m.start())]
            if len(hits) < 2:
                continue
            paired = all(_call_slot(clean, body_start + m.start()) in siblings for m in hits)
            plans.append((setup_end, line_start, body_start, body_end, array, hits, paired))
    return opening, plans


def _apply(source, opening, plans):
    names = set(re.findall(r'\b' + I + r'\b', _blank(source)))
    edits = []
    decls = []
    for setup_end, line_start, body_start, body_end, array, hits, _ in plans:
        local = array + '_arg'
        n = 2
        while local in names:
            local = '%s_arg%d' % (array, n)
            n += 1
        names.add(local)
        indent = re.match(r'[ \t]*', source[line_start:]).group(0)
        edits.append((setup_end, setup_end, '%s%s = &%s;\n' % (indent, local, array)))
        for m in hits:
            edits.append((body_start + m.start(), body_start + m.end(),
                          m['pre'] + (m['cast'] or '') + local))
        decls.append('  %s *%s;\n' % (_element_type(source, array), local))
    edits.sort(key=lambda e: e[0], reverse=True)
    text = source
    for a, b, new in edits:
        text = text[:a] + new + text[b:]
    after = text.find('\n', opening) + 1
    return text[:after] + ''.join(decls) + text[after:]


def variants(source, name):
    opening, plans = _plan(source, name)
    if not plans:
        return []
    out = [(FAMILY, _apply(source, opening, [p])) for p in plans]
    paired = [p for p in plans if p[-1]]
    if len(paired) > 1:
        out.insert(0, (COMBINED, _apply(source, opening, paired)))
    return out[:12]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
