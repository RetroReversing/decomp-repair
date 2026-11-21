"""A float field each arm of an if/else recomputes, written the way the game wrote it.

When both arms of an `if` end by giving one float field a new value, gcc merges the two stores into one after the
join, and a draft reads that back as a result variable each arm sets, stored once:

    if (c) {
        r = (limit - y) * 30.0f;
        v = obj->speed;
        r = (f32)((f64)(r - v) * K + (f64)v);
    } else {
        r = scale * 14.999999f;
    }
    obj->speed = r;

The instructions are then the target's, but the float registers trade places: which value the result is tied to,
and which register a product's operand and its constant take, follow from how each arm is written. An
836-instruction N64 function (KMC GCC 2.7.2, -O2) was six `$f0`/`$f2` operands from exact this way, and exact as

    if (c) {
        r = (limit - y) * 30.0f;
        obj->speed += (f64)(r - obj->speed) * K;
    } else {
        r = scale;
        obj->speed = r * 14.999999f;
    }

Two rewrites, offered together first and then each alone:

- `float_arm_update`: the store goes into each arm, and an arm that adds to the field's old value updates it in
  place. The old value is then loaded after what is added to it and tied to the result.
- `float_arm_shared_local`: a float local one arm keeps to itself also holds the leading operand of the other arm's
  store. Used in two blocks, it gets its register from the function-wide pass rather than the block's, in both arms.

Neither changes what is computed: an addition's sides trade places, and a float is copied through a float.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

UPDATE = 'float_arm_update'
SHARED = 'float_arm_shared_local'
BOTH = 'float_arm_roles'
FAMILIES = (BOTH, UPDATE, SHARED)

IDENT = r'[A-Za-z_]\w*'
FLOAT = r'(?:f32|float)'
DOUBLE = r'(?:f64|double)'
LIMIT = 2  # if/else sites per rewrite: the float lane that asks is a short one


def variants(source, name, header=''):
    updated = _update(source, name)
    result = []
    for candidate in updated:
        result += [(BOTH, text) for text in _shared(candidate, name, header)[:1]]
    result += [(UPDATE, text) for text in updated]
    result += [(SHARED, text) for text in _shared(source, name, header)]
    seen = set()
    return [(family, text) for family, text in result if not (text in seen or seen.add(text))]


def _body(source, name):
    span = find(source, name)
    clean = _blank(source)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return None
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, opening, end) if end else None


def _opening_brace(text, closing):
    depth = 0
    for pos in range(closing, -1, -1):
        depth += (text[pos] == '}') - (text[pos] == '{')
        if depth == 0:
            return pos
    return None


def _arms(clean, closing):
    """The two arms `(start, end)` of the if/else whose else block closes at `closing` (the `}`), or None."""
    else_open = _opening_brace(clean, closing)
    keyword = re.search(r'\belse\s*$', clean[:else_open]) if else_open is not None else None
    if not keyword:
        return None
    if_close = len(clean[:keyword.start()].rstrip())
    if clean[if_close - 1:if_close] != '}':
        return None
    if_open = _opening_brace(clean, if_close - 1)
    if if_open is None or not re.search(r'\)\s*$', clean[:if_open]):
        return None
    return (if_open + 1, if_close - 1), (else_open + 1, closing)


def _statements(clean, start, end):
    """The arm's top-level statements as `(start, end)`, `end` past the `;`; None for a nested block's place."""
    result = []
    depth = 0
    at = None
    for pos in range(start, end):
        char = clean[pos]
        if at is None and not char.isspace() and depth == 0 and char not in '{}':
            at = pos
        if char in '({[':
            depth += 1
        elif char in ')}]':
            depth -= 1
            if char == '}' and depth == 0:
                result.append(None)
                at = None
        elif char == ';' and depth == 0 and at is not None:
            result.append((at, pos + 1))
            at = None
    return result if at is None and depth == 0 else None


def _spaces(text):
    return re.sub(r'\s+', '', text)


def _operators(text):
    """Positions of the binary operators outside every bracket, as `(position, operator)`."""
    result = []
    depth = 0
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and text.startswith('->', pos):
            pos += 2
            continue
        elif depth == 0 and char in '+-*/%<>=!&|^?:,':
            before = text[:pos].rstrip()[-1:]
            # a sign or a pointer's star after an operator, a cast or nothing is part of its operand
            binary = (before.isalnum() or before in ('_', ')', ']')) and not _after_cast(text, pos)
            width = 2 if text[pos:pos + 2] in ('<<', '>>', '==', '!=', '<=', '>=', '&&', '||', '++', '--') else 1
            if binary or char not in '+-*&':
                result.append((pos, text[pos:pos + width]))
            pos += width
            continue
        pos += 1
    return result


def _after_cast(text, pos):
    """Whether the `)` before `pos` closes a cast: `(f64) -x`, `(s32 *) *p`."""
    before = text[:pos].rstrip()
    if not before.endswith(')'):
        return False
    depth = 0
    for start in range(len(before) - 1, -1, -1):
        depth += (before[start] == ')') - (before[start] == '(')
        if depth == 0:
            inside = before[start + 1:-1].strip()
            return bool(re.fullmatch(rf'(?:const\s+|unsigned\s+|signed\s+|struct\s+)*{IDENT}(?:\s*\*+)?', inside)
                        and re.fullmatch(r'[fsu](?:8|16|32|64)|float|double|int|char|short|long|\w+_t|.*\*', inside))
    return False


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _in_place(rhs, lhs, old):
    """What `rhs` adds to the field's old value, when it is `X + old` or `old + X`; None otherwise.

    `old` is the local holding the field's value (or None: only the field's own text counts). The sum may sit in
    a float cast, and the old value in a double one when what is added is already a double.
    """
    rhs = _unwrap(rhs)
    cast = re.match(rf'\(\s*{FLOAT}\s*\)\s*(?=\()', rhs)
    if cast and close(rhs, cast.end()) == len(rhs):
        rhs = _unwrap(rhs[cast.end():])
    operators = _operators(rhs)
    if [op for _, op in operators if op not in ('*', '/')] != ['+']:
        return None
    plus = next(pos for pos, op in operators if op == '+')
    if any(pos > plus for pos, _ in operators) and any(pos < plus for pos, _ in operators):
        return None
    sides = rhs[:plus].strip(), rhs[plus + 1:].strip()
    for mine, other in (sides, sides[::-1]):
        widened = re.match(rf'\(\s*{DOUBLE}\s*\)\s*', mine)
        value = _unwrap(mine[widened.end():] if widened else mine)
        if value != old and _spaces(value) != _spaces(lhs):
            continue
        # a double sum of two floats rounds twice, a float sum once: keep the precision the draft computed in
        if widened and not re.match(rf'\(\s*{DOUBLE}\s*\)', other):
            continue
        if not widened and re.search(rf'\(\s*{DOUBLE}\s*\)', other):
            continue
        return other
    return None


def _calls(text):
    return re.search(rf'(?<![\w.>]){IDENT}\s*\(', re.sub(r'\bM2C_FIELD\s*\(', '(', text)) or re.search(r'\+\+|--', text)


def _update(source, name):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    result = []
    store = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;={}\n]+?)\s*=(?!=)\s*(?P<var>' + IDENT + r')\s*;[ \t]*\n')
    for hit in store.finditer(clean, opening, end):
        var, lhs = hit['var'], source[hit.start('lhs'):hit.end('lhs')].strip()
        mention = re.compile(r'(?<![\w.>])' + var + r'\b')
        if mention.search(lhs) or _calls(lhs):
            continue
        if not re.search(rf'(?m)^[ \t]*{FLOAT}\s+{var}\s*;', clean[opening:hit.start()]):
            continue
        before = clean[:hit.start()].rstrip()
        arms = _arms(clean, len(before) - 1) if before.endswith('}') else None
        if not arms:
            continue
        # the variable carries nothing in or out: every other mention is inside the two arms
        outside = [m.start() for m in mention.finditer(clean, opening, end)
                   if not any(a <= m.start() < b for a, b in arms) and not hit.start() <= m.start() < hit.end()]
        if len(outside) != 1:  # its declaration
            continue
        edits = [(hit.start(), hit.end(), '')]
        updated = False
        for a, b in arms:
            statements = _statements(clean, a, b)
            last = statements[-1] if statements else None
            assign = re.fullmatch(var + r'\s*=(?!=)\s*(?P<rhs>[^;]+);', clean[last[0]:last[1]]) if last else None
            if not assign:
                edits = None
                break
            rhs = source[last[0] + assign.start('rhs'):last[0] + assign.end('rhs')]
            previous = statements[-2] if len(statements) > 1 else None
            copy = re.fullmatch(rf'(?P<old>{IDENT})\s*=(?!=)\s*(?P<from>[^;]+);', clean[previous[0]:previous[1]]) if previous else None
            old = copy['old'] if copy and copy['old'] != var and _spaces(copy['from']) == _spaces(lhs) else None
            added = _in_place(rhs, lhs, old)
            if added is None:
                edits.append((last[0], last[1], f'{lhs} = {rhs.strip()};'))
                continue
            updated = True
            if old:
                added = re.sub(r'(?<![\w.>])' + old + r'\b', lhs.replace('\\', r'\\'), added)
                elsewhere = [m for m in re.finditer(r'(?<![\w.>])' + old + r'\b', clean[opening:end])
                             if not previous[0] <= opening + m.start() < last[1]]
                if len(elsewhere) == 1:  # only its declaration: the copy has no reader left
                    line = clean.rfind('\n', 0, previous[0]) + 1
                    edits.append((line, clean.find('\n', previous[1]) + 1, ''))
            edits.append((last[0], last[1], f'{lhs} += {added};'))
        if not edits or not updated:
            continue
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        result.append(text)
        if len(result) >= LIMIT:
            break
    return result


def _float_load(text, context):
    """Whether `text` reads a float without doing anything else: a float local, field or element."""
    text = _unwrap(text)
    if re.fullmatch(rf'M2C_FIELD\s*\(\s*[^,()]+,\s*{FLOAT}\s*\*\s*,\s*\w+\s*\)', text):
        return True
    if _calls(text) or not re.fullmatch(rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT}|\s*\[\s*\w+\s*\])*', text):
        return False
    names = re.findall(IDENT, text)
    # a member is declared in its record (`f32 x, y, z;`); a local or a parameter may also end at `)` or `=`
    after = '[;,]' if len(names) > 1 or '[' in text else '[;,=)]'
    return bool(re.search(rf'\b{FLOAT}\s+(?:{IDENT}\s*(?:\[\w*\])?\s*,\s*)*{names[-1]}\b\s*(?:\[\w*\])?\s*{after}', context))


def _stored(clean, statement):
    """`(place, operator, value span)` of a `place = value;` or `place += value;` statement, or None."""
    hit = re.fullmatch(r'(?P<lhs>[^;=]+?)\s*(?P<op>[-+*/]?=)(?!=)\s*(?P<rhs>[^;]+);', clean[statement[0]:statement[1]])
    if not hit or hit['lhs'].rstrip()[-1:] in '<>!':
        return None
    return hit['lhs'].strip(), hit['op'], (statement[0] + hit.start('rhs'), statement[0] + hit.end('rhs'))


def _shared(source, name, header=''):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    context = _blank(header) + '\n' + clean
    result = []
    for keyword in re.finditer(r'\belse\s*\{', clean[opening:end]):
        closing = close(clean, opening + keyword.end() - 1, '{', '}')
        arms = _arms(clean, closing - 1) if closing else None
        if not arms:
            continue
        lasts = []
        for a, b in arms:
            statements = _statements(clean, a, b)
            lasts.append(_stored(clean, statements[-1]) if statements and statements[-1] else None)
        if not all(lasts) or _spaces(lasts[0][0]) != _spaces(lasts[1][0]) or _calls(lasts[0][0]):
            continue
        if re.fullmatch(IDENT, lasts[0][0]):  # a result variable, not the field: `float_arm_update` comes first
            continue
        for keeper, other in ((0, 1), (1, 0)):
            a, b = arms[keeper]
            # float locals the keeping arm sets as whole statements, and nothing else in the function mentions
            for local in dict.fromkeys(re.findall(rf'(?m)^[ \t]*({IDENT})\s*=(?!=)', clean[a:b])):
                mention = re.compile(r'(?<![\w.>])' + local + r'\b')
                outside = [m for m in mention.finditer(clean, opening, end) if not a <= m.start() < b]
                if len(outside) != 1 or not re.search(rf'(?m)^[ \t]*{FLOAT}\s+{local}\s*;', clean[opening:arms[0][0]]):
                    continue
                place, operator, (start, stop) = lasts[other]
                value = source[start:stop]
                operators = _operators(value)
                if operator != '=' or len(operators) != 1 or operators[0][1] not in ('*', '/', '+', '-'):
                    continue
                lead = value[:operators[0][0]]
                if not _float_load(lead, context) or mention.search(place):
                    continue
                line = clean.rfind('\n', 0, start) + 1
                indent = re.match(r'[ \t]*', source[line:])[0]
                statement = clean.rfind(place[:1], line, start)
                if clean[line:statement].strip():
                    continue
                text = (source[:line] + f'{indent}{local} = {lead.strip()};\n' + source[line:start]
                        + local + ' ' + value[operators[0][0]:].lstrip() + source[stop:])
                result.append(text)
                break
            if len(result) >= LIMIT:
                return result
    return result
