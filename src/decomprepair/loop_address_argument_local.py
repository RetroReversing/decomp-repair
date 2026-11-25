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

`loop_address_argument_local_outer`: the same naming for a loop of any kind (`for (;;)`, `while`, `do`) whose body
holds other loops, with every call argument `&X` in the whole body read through the one local, set before that loop
beside its siblings. A 2,267-instruction collision sweep (KMC gcc 2.7.2) builds an object walk (m2c's `for (;;)`)
around two triangle loops, one a `do`, one a goto loop, inside the retry walk's `do`: the target computes `&spD0` once
per walk into `$s7` (`addiu $s7, $sp, 0xD0` beside the walk's other pointer locals) and passes `$s7` to every call,
where `&spD0` in each call compiled to a fresh address the loop pass hoists out of the retry loop and reload spills.
Named before the walk, 7228 -> 4793 (one function). Hypothesis from the 2.7.2 source: loop.c `scan_loop` moves a user
variable's set out of a loop only when it is executed on every iteration (not after a jump in the loop body), and the
walk's head sits after the actor loop's branches, so the named pointer stays in its register for the whole walk.
Struct copies through the address (`*((T *) (&X)) = ...`) are left as they are: the target reads them off `$sp`.
"""
import re

from .csource import _blank, find

FAMILY = 'loop_address_argument_local'
COMBINED = 'loop_address_argument_local_all'
OUTER = 'loop_address_argument_local_outer'
FAMILIES = (FAMILY, COMBINED, OUTER)

I = r'[A-Za-z_]\w*'


def _python_loops(clean, start, end):
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


_loops = _python_loops
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _loops(clean, start, end):
        if end > len(clean):
            return _python_loops(clean, start, end)
        out = []
        for m in re.finditer(r'\bdo\s*\{', clean[start:end]):
            opening = start + m.end() - 1
            k = _scan.close_if(clean, opening, '{', '}', None)
            if k is NotImplemented:
                return _python_loops(clean, start, end)
            if k is not None and k < end:
                out.append((start + m.start(), opening + 1, k))
        return out


def _enclosing_loops(clean, start, end):
    """(keyword-start, body-start, body-end) of each `for (...) {`, `while (...) {` or `do {` in [start, end) whose
    body holds another loop (a `do`, `for`, `while` or a label that a `goto` in the body jumps back to)."""
    out = []
    for m in re.finditer(r'\b(?:do|for\s*\([^;{}()]*;[^;{}()]*;[^{}()]*\)|while\s*\((?:[^(){};]|\([^(){};]*\))*\))\s*\{',
                         clean[start:end]):
        opening = start + m.end() - 1
        depth = 0
        for k in range(opening, end):
            if clean[k] == '{':
                depth += 1
            elif clean[k] == '}':
                depth -= 1
                if depth == 0:
                    body = clean[opening + 1:k]
                    labels = re.findall(r'(?m)^\s*(' + I + r')\s*:(?!:)', body) + re.findall(r'[;{}]\s*(' + I + r')\s*:(?!:)', body)
                    inner = re.search(r'\b(?:do\s*\{|for\s*\(|while\s*\()', body) or any(
                        re.search(r'\bgoto\s+' + lab + r'\s*;', body) for lab in labels if lab != 'default')
                    if inner:
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


def _outer_plans(source, name):
    span = find(source, name)
    if not span:
        return None, []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None, []
    plans = []
    for loop_at, body_start, body_end in _enclosing_loops(clean, opening, span[1]):
        setup_end, line_start = _pointer_setups(source, clean, loop_at)
        body = clean[body_start:body_end]
        for array in sorted(set(re.findall(r'&\s*\(?\s*(' + I + r')\b', body))):
            hits = [m for m in _argument(array).finditer(body) if _call_slot(clean, body_start + m.start())]
            if len(hits) < 2:
                continue
            plans.append((setup_end, line_start, body_start, body_end, array, hits, False))
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
    out = [(FAMILY, _apply(source, opening, [p])) for p in plans]
    paired = [p for p in plans if p[-1]]
    if len(paired) > 1:
        out.insert(0, (COMBINED, _apply(source, opening, paired)))
    outer_opening, outer = _outer_plans(source, name)
    # The innermost enclosing loops first: the walk around the triangle loops before the function-wide retry loop.
    outer.sort(key=lambda p: (p[3] - p[2], p[0]))
    out += [(OUTER, _apply(source, outer_opening, [p])) for p in outer[:8]]
    return out[:20]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
