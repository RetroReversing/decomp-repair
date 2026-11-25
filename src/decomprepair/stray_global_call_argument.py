"""A global m2c passed as a callee's trailing argument because the register still held it, taken out with the prototype.

m2c names whatever an argument register holds at a call. When the caller has just stored a global cursor and the value is
still in `$a1`, it writes the global as a second argument (`func(e->id, sDisplayListCursor);`) and a prototype to fit
(`s32 func(s32, void *);`), although the callee (a display-list helper that reads the cursor itself) takes one argument.
KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) compiles that extra argument into a copy to `$a1` the target does not have,
and the copy changes the code before it: a 525-instruction N64 display-list builder that ended a two-command write with
`cursor += 1; cursor += 1; helper(id, cursor);` had the cursor's `gp + 16` scheduled before `gp + 8` and the cursor in
`$a2`, nine rows that a dozen spellings of the two stores did not move (55); dropping the argument was exact (55 -> 0).
The reading is a hypothesis from sched.c (the first scheduler launches an insn just before its consumer only when its
destination is set once, `birthing_insn_p`, and the copy to `$a1` is a second consumer of the sum); the judge decides.

The shape: a call whose last argument is a bare global variable (declared `extern` in the source or the project header,
never an array, a local, a parameter, a function or an address, and not passed in another slot too), to a callee the source itself declares with exactly that many
parameters. One child per callee drops that argument from every call of it in the function and the last parameter from
its prototype; with several such callees, one more child drops them all. A callee the header declares is left alone (the
call would no longer fit its declaration), as is one the function calls with differing argument counts.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'stray_global_call_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
CALL = re.compile(rf'(?<![\w.>])(?P<f>{IDENT})\s*\(')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do'}


def _blank(text):
    """Comments and string literals blanked to spaces, offsets kept."""
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'',
                  lambda m: re.sub(r'[^\n]', ' ', m.group()), text, flags=re.S)


def _python_arguments(clean, start, end):
    """The top-level argument spans between `start` (just after `(`) and `end` (the `)`)."""
    spans, depth, begin = [], 0, start
    for index in range(start, end):
        char = clean[index]
        depth += (char in '([{') - (char in ')]}')
        if char == ',' and depth == 0:
            spans.append((begin, index))
            begin = index + 1
    if clean[begin:end].strip():
        spans.append((begin, end))
    return spans


_arguments = _python_arguments
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _arguments(clean, start, end):
        found = _scan.argument_spans(clean, start, end)
        return _python_arguments(clean, start, end) if found is NotImplemented else found


def _globals(text):
    """Names declared `extern` as variables (not functions) in `text`."""
    names = set()
    for hit in re.finditer(r'(?m)^[ \t]*extern\b([^;(){}]*);', text):
        if '[' in hit[1].split('=')[0]:
            continue  # an array is passed as its address, never as a register's leftover value
        found = re.findall(IDENT, hit[1].split('=')[0])
        if found:
            names.add(found[-1])
    return names


def _prototype(clean, limit, callee):
    """The source's own prototype of `callee` before `limit`: (start of its parameter list, its `)`, parameter spans)."""
    found = None
    for hit in re.finditer(rf'(?m)^[^\n;{{}}()]*\b{re.escape(callee)}\s*\(', clean[:limit]):
        end = close(clean, hit.end() - 1, '(', ')')
        if not end or not re.match(r'\s*;', clean[end:]):
            continue
        found = (hit.end(), end - 1, _arguments(clean, hit.end(), end - 1))
    return found


def _declared(clean, callee):
    return re.search(rf'(?<![\w.>]){re.escape(callee)}\s*\(', clean) is not None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    header_clean = _blank(header or '')
    globals_ = _globals(clean[:part.opening]) | _globals(header_clean)
    signature = clean[:part.opening]
    params = set(re.findall(rf'({IDENT})\s*(?:,|\)|\[)', signature[signature.rfind('(') + 1:] + ')'))
    body = clean[part.opening + 1:part.end]
    calls = {}
    for hit in CALL.finditer(clean, part.opening + 1, part.end):
        callee = hit['f']
        if callee in KEYWORDS:
            continue
        end = close(clean, hit.end() - 1, '(', ')')
        if not end:
            continue
        calls.setdefault(callee, []).append((hit.end(), end - 1, _arguments(clean, hit.end(), end - 1)))
    per_callee = []
    for callee, sites in calls.items():
        counts = {len(spans) for _, _, spans in sites}
        if len(counts) != 1 or counts == {0} or (header_clean and _declared(header_clean, callee)):
            continue
        count = counts.pop()
        prototype = _prototype(clean, part.opening, callee)
        if not prototype or len(prototype[2]) != count:
            continue
        stray = {clean[spans[-1][0]:spans[-1][1]].strip() for _, _, spans in sites}
        if len(stray) != 1:
            continue
        value = stray.pop()
        if any(value == clean[a:b].strip() for _, _, spans in sites for a, b in spans[:-1]):
            continue  # also passed in another slot: a real argument passed twice
        if (not re.fullmatch(IDENT, value) or value not in globals_ or value in params
                or re.search(rf'(?m)^[ \t]*(?:{IDENT}[ \t*]+)+{re.escape(value)}\s*(?:\[[^\]]*\])?\s*[;=,]', body)):
            continue  # a bare global only: a local or parameter of that name shadows it
        edits = []
        for _, _, spans in sites:
            begin = spans[-2][1] if count > 1 else spans[-1][0]
            edits.append((begin, spans[-1][1], ''))
        _, _, proto_spans = prototype
        begin = proto_spans[-2][1] if count > 1 else proto_spans[-1][0]
        edits.append((begin, proto_spans[-1][1], '' if count > 1 else 'void'))
        per_callee.append(edits)
    out = [(FAMILY, edit(source, edits)) for edits in per_callee]
    if len(per_callee) > 1:
        out.append((FAMILY, edit(source, [e for edits in per_callee for e in edits])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 50}  # the registry: no caller wiring (registry.py)
