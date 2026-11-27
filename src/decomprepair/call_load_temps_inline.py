"""Memory reads staged in temporaries before a call, written back into the call's argument.

m2c gives each byte a call packs into a word a temporary of its own, in the order of the target's load registers, and
steps the pointer it read them through between the loads and the call:

    temp_a2 = *(u8 *) (var_s3 + 0);
    temp_v0 = *(u8 *) (var_s3 - 2);
    temp_v1 = *(u8 *) (var_s3 - 1);
    var_s3 += 4;
    store(dst, (*var_s2 << 24) | (temp_v0 << 16) | (temp_v1 << 8) | temp_a2, temp_a2);

The temporaries fix the order of the loads (the statements'), where the source had one expression and the compiler
loaded in its order of evaluation. The child writes each read where its temporary was used and moves the pointer's
step after the call. The last argument above is m2c's guess from a register that still held a value, so a second child
(offered first) also drops a trailing argument that only repeats one of the temporaries, and the last parameter of a
prototype in the source that counts it.

A memcpy-like ROM write built by SN GCC 2.8.1 (`-G0 -mips3 -O2`) went from 250 to 100 with this alone and to 0 with
`loop_top_cursor_copy` on its byte-wise tail.

Only plain reads move: a cast dereference of the temporary's own width (or narrower unsigned read into a wider signed
or equal local), `*P` or `P[K]` of a `T *P` with `T` the temporary's type. Each temporary is written once and read only
by that call, the call holds no other call or write, and a stepped pointer is not named by the call itself, so it reads
the same values. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'call_load_temps_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
_TYPE = r'(?:u8|s8|u16|s16|u32|s32|f32)'
# which local types hold every value of a read of the key's type unchanged
_HOLDS = {'u8': ('u8', 's16', 'u16', 's32'), 's8': ('s8', 's16', 's32'), 'u16': ('u16', 's32'),
          's16': ('s16', 's32'), 'u32': ('u32',), 's32': ('s32',), 'f32': ('f32',)}
_LOAD = re.compile(rf'(?P<t>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}=]+);')
_STEP_TEXT = rf'(?P<p>{IDENT})\s*(?:\+=|-=)\s*{NUMBER}\s*;'
_STEPS = (re.compile(rf'do\s*\{{\s*{_STEP_TEXT}\s*\}}\s*while\s*\(\s*0\s*\)\s*;'),
          re.compile(rf'\{{\s*{_STEP_TEXT}\s*\}}'), re.compile(_STEP_TEXT))
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof|do|else)\b)(?P<f>{IDENT})\s*\(')


def _declared(clean, name):
    """(type, is pointer) of the one declaration of `name`, or None."""
    found = re.findall(rf'(?<![\w.>])({_TYPE}|void|char)\s*(\*?)\s*(?<![\w]){re.escape(name)}\b\s*(?=[;,)])', clean)
    return (found[0][0], bool(found[0][1])) if len(found) == 1 else None


def _own(clean, part, name):
    """True when `name` is a parameter or a local of the function."""
    signature = clean[clean.rfind('\n', 0, clean.rfind('(', 0, part.opening)) + 1:part.opening]
    declaration = rf'(?<![\w.>]){IDENT}[\s*]+{re.escape(name)}\s*(?=[;,)=])'
    return bool(re.search(declaration, signature) or re.search(r'(?m)^[ \t]*(?:register\s+)?' + declaration, part.body))


def _read(clean, expression):
    """The type a plain memory read yields, or None when the expression is anything else."""
    text = expression.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    if re.search(rf'\+\+|--|\bvolatile\b|(?<!\bsizeof)(?<![*\s(])(?<=\w)\s*\((?!\s*{_TYPE}\s*\*)', text):
        return None
    cast = re.match(r'\*\s*(?=\()', text)
    if cast:
        rest = text[cast.end():]
        # `*(T *)(...)` or `*((T *)(...))`
        direct = re.match(rf'\(\s*({_TYPE})\s*\*\s*\)\s*', rest)
        if direct:
            tail = rest[direct.end():]
            if tail.startswith('(') and close(tail, 0, '(', ')') == len(tail) or re.fullmatch(IDENT, tail):
                return direct[1]
            return None
        if close(rest, 0, '(', ')') == len(rest):
            inner = re.match(rf'\(\s*\(\s*({_TYPE})\s*\*\s*\)', rest)
            return inner[1] if inner else None
        if re.fullmatch(IDENT, rest):
            declared = _declared(clean, rest)
            return declared[0] if declared and declared[1] else None
        return None
    plain = re.fullmatch(rf'\*\s*({IDENT})', text) or re.fullmatch(rf'({IDENT})\s*\[\s*-?\s*{NUMBER}\s*\]', text)
    if plain:
        declared = _declared(clean, plain[1])
        return declared[0] if declared and declared[1] else None
    return None


def _backwards(clean, low, at):
    """The loads and pointer steps right before `at`, in source order: (start, end, kind, match)."""
    found = []
    while True:
        head = clean[low:at].rstrip()
        end = low + len(head)
        starts = [m.start() for m in re.finditer(r'[;{}]', head)]
        item = None
        for start in reversed(starts[-8:] if len(starts) > 8 else starts):
            text = head[start + 1:]
            stripped = text.lstrip()
            begin = low + start + 1 + len(text) - len(stripped)
            step = next((m for m in (pattern.fullmatch(stripped) for pattern in _STEPS) if m), None)
            if step:
                item = (begin, end, 'step', step)
                break
            load = _LOAD.fullmatch(stripped)
            if load:
                item = (begin, end, 'load', load)
                break
        if item is None:
            # the first statement of the block
            stripped = head.lstrip()
            begin = low + len(head) - len(stripped)
            load = _LOAD.fullmatch(stripped)
            item = (begin, end, 'load', load) if load else None
        if item is None:
            return found
        found.insert(0, item)
        at = item[0]


def _call_statement(clean, hit, low):
    """(start, end, arguments' spans) of the statement that is this call, `f(...);` or `x = f(...);`."""
    opening = hit.end() - 1
    closing = close(clean, opening, '(', ')')
    if not closing or not re.match(r'\s*;', clean[closing:]):
        return None
    start = max(clean.rfind(mark, low, hit.start()) for mark in ';{}') + 1
    start = max(start, low)
    lead = clean[start:hit.start()]
    if not re.fullmatch(rf'\s*(?:{IDENT}\s*=\s*)?', lead):
        return None
    start += len(lead) - len(lead.lstrip())
    spans, depth, last = [], 0, opening + 1
    for at in range(opening + 1, closing - 1):
        depth += (clean[at] in '([') - (clean[at] in ')]')
        if clean[at] == ',' and depth == 0:
            spans.append((last, at))
            last = at + 1
    spans.append((last, closing - 1))
    inside = clean[opening + 1:closing - 1]
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', inside):
        return None
    if any(not re.fullmatch(rf'{_TYPE}|void|char', m['f']) for m in _CALL.finditer(inside)):
        return None
    return start, closing + len(re.match(r'\s*;', clean[closing:])[0]), spans


def _line(source, start, end):
    first = source.rfind('\n', 0, start) + 1
    last = source.find('\n', end)
    if not source[first:start].strip() and last >= 0 and not source[end:last].strip():
        return first, last + 1
    return start, end


def _prototype_trim(source, clean, body_start, callee, count):
    """The edit that drops the last parameter of a prototype of `callee` with `count` parameters, or []."""
    for hit in re.finditer(rf'(?<![\w.]){re.escape(callee)}\s*\(([^()]*)\)\s*;', clean[:body_start]):
        parameters = hit[1].split(',')
        if len(parameters) == count and '...' not in hit[1]:
            return [(hit.start(1) + hit[1].rfind(','), hit.end(1), '')]
    return []


def _children(source, part, hit):
    clean, low = part.clean, part.opening + 1
    statement = _call_statement(clean, hit, low)
    if not statement:
        return []
    start, end, spans = statement
    run = _backwards(clean, low, start)
    stray = len(spans) - 1 if len(spans) > 1 else None
    loads, stepped, steps = [], set(), []
    for item in run:
        begin, stop, kind, match = item
        if kind == 'step':
            steps.append(item)
            stepped.add(match['p'])
            continue
        name, expression = match['t'], match['e']
        declared = _declared(clean, name)
        kind_read = _read(clean, expression)
        # a read after a step of its own pointer would see the old value once the step moves down
        if (not declared or declared[1] or kind_read is None or declared[0] not in _HOLDS.get(kind_read, ())
                or stepped & set(re.findall(IDENT, expression))):
            loads, stepped, steps = [], set(), []
            continue
        uses = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[low:part.end])]
        inside = [low + m.start() for m in uses if hit.end() <= low + m.start() < end]
        writes = [m for m in uses if re.match(r'\s*(?:=(?!=)|[-+*/|&^]=|<<=|>>=|\+\+|--)', clean[low + m.end():])]
        extra = [at for at in inside if stray is not None and clean[spans[stray][0]:spans[stray][1]].strip() == name
                 and spans[stray][0] <= at < spans[stray][1]]
        # declaration, the load, then only this call's reads
        if len(writes) != 1 or len(uses) != 2 + len(inside) or not inside or len(inside) > 1 + len(extra):
            loads, stepped, steps = [], set(), []
            continue
        loads.append((begin, stop, name, expression.strip(), inside, extra))
    if not loads:
        return []
    first = min(item[0] for item in loads)
    steps = [item for item in steps if item[0] > first]
    named = set(re.findall(IDENT, clean[hit.end():end]))
    # the pointer is this function's own and nothing else holds its address, so the callee cannot see when it moves
    for item in steps:
        pointer = item[3]['p']
        if pointer in named or not _own(clean, part, pointer) or _address_taken(part.body, pointer):
            return []
    # no read may name a temporary that is moving too
    names = {item[2] for item in loads}
    if any(names & set(re.findall(IDENT, item[3])) for item in loads):
        return []
    moved = ''.join(' ' + source[item[0]:item[1]] for item in steps)

    def child(drop):
        edits = []
        gone = None
        for begin, stop, name, expression, inside, extra in loads:
            if drop and extra and len(inside) > 1:
                gone = name
        if drop and gone is None:
            return None
        for begin, stop, name, expression, inside, extra in loads:
            edits.append(_line(source, begin, stop) + ('',))
            text = expression if expression.startswith('(') and close(expression, 0, '(', ')') == len(expression) \
                else f'({expression})'
            for at in inside:
                if name == gone and at in extra:
                    continue
                edits.append((at, at + len(name), text))
        for item in steps:
            edits.append(_line(source, item[0], item[1]) + ('',))
        if moved:
            edits.append((end, end, moved))
        if drop:
            previous = spans[stray - 1][1]
            edits.append((previous, spans[stray][1], ''))
            edits += _prototype_trim(source, clean, part.opening, hit['f'], len(spans))
        # a temporary left without a use loses its declaration
        for begin, stop, name, *_ in loads:
            declaration = re.search(rf'(?m)^[ \t]*{_TYPE}[ \t]+{re.escape(name)}[ \t]*;[ \t]*\n', clean[low:part.end])
            if declaration:
                edits.append((low + declaration.start(), low + declaration.end(), ''))
        return edit(source, edits)

    # an argument that stays a second use of its temporary has nothing to be written as, unless it is folded too
    plain = child(False)
    return [text for text in (child(True), plain) if text]


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    result = []
    for hit in _CALL.finditer(part.clean, part.opening + 1, part.end):
        for text in _children(source, part, hit):
            if text != source:
                result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
