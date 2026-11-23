"""A `switch` whose arms `goto` labels inside the switch, written as arms that each carry their own copy of the run.

m2c merges what the compiler's cross-jumping had merged, inside the switch too:

    case 46: v = P->flags; mask = 0xFE1FFFFF; kind = 0x2F; goto set_kind;
    case 44: v = P->flags; mask = 0xFE1FFFFF; kind = 0x2C; goto set_kind;
    ...
    case 49: v = P->flags; mask = 0xFE1FFFFF; kind = 0x32;
    set_kind: P->kind = kind; flag = 0x600000;
    apply: v &= mask; v |= flag; P->flags = v; break;

so every arm shares one `v`, one `mask`, one `kind` and one `flag`: function-wide pseudos with a dozen arms' references,
which `global.c` ranks above anything an arm needs and hands `$v1`/`$a0`, and every arm's registers follow. The game
wrote each arm out (`P->kind = 0x2F; P->flags = (P->flags & 0xFE1FFFFF) | 0x600000; break;`) and the compiler merged the
identical tails again after allocation (`jump2`), so each arm's temporaries are block-local pseudos that `local-alloc.c`
colours arm by arm. `switch_goto_tail_arms` copies runs that sit after the switch; here the labels are inside it, and
several things change together or the judge sees nothing (each alone leaves the shared web, or scores worse):

- the run is copied into every arm that jumps to it (the arm that reaches it by falling through keeps its own), a
  `do { ... } while (0)` around such a `goto` is unwrapped (a `break` inside it would leave only that loop), and an
  arm that only the `goto`s reached is dropped;
- the scratch locals that only this switch reads (`v`, `mask`, `kind`, `flag`) are declared inside each arm that uses
  them, so each arm has pseudos of its own;
- a local set once to a literal is written as the literal (`mask` is `0xFE1FFFFF`, `kind` is `0x2F`);
- `t = v & mask; P->flags = t | flag;` is the compound update `v &= mask; v |= flag; P->flags = v;`;
- (`switch_label_arms_mixed`) a word update written `P->flags = (P->flags & M) | K;` gets the same compound form on a
  local of its own, and the statements of the arm that come before it sit between its `|=` and its store: the first
  scheduler then loads the word before it builds the mask (`lw`, `lui`, `ori`), as the target does, and an arm's
  `D = D + 1;` or `P->kind = K;` is where the target has it.

A KMC GCC 2.7.2 N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`, 713 instructions, a 51-case switch whose arms set a
kind byte and a flag word) was written this way: the arms' registers went from `$v1`/`$a0` exchanged in 29 rows to none
(2505 against 1570 with the next two steps), and with the second switch's range (`switch_range_trim`), the plain read of
the word (`volatile_cast_unpin`), the return width (`narrow_return_compare`) and the flag scope of
`parameter_test_scope` the whole function matched (1855 -> 0 in the isolated judge). Why the original arms allocate this
way is read from `-dl -dg` (the priorities of the shared pseudos), the compiler source gives no more than that: a
hypothesis, the judge decides.

`variants` takes each `switch` whose `goto`s all go to labels of its own body and sit where it can rewrite them (a
top-level `goto L;` or the last statement of a top-level `do { } while (0)`), and offers as one child each of the
rewrites above (the arms are only right together): without the mixed update, with it, and each with the flag scope of
`parameter_test_scope` for the parameters it proposes (`switch_label_arms_scoped`)."""
import re

from . import parameter_test_scope
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'switch_label_arms'
MIXED = 'switch_label_arms_mixed'
SCOPED = 'switch_label_arms_scoped'
FAMILIES = (FAMILY, MIXED, SCOPED)
SCOPE_LIMIT = 3
LITERAL = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
_SWITCH = re.compile(r'\bswitch\s*\(')
_CASE = re.compile(r'(?:case\b[^:;{}?]*:|default\s*:)')
_LABEL = re.compile(rf'(?!(?:case|default|else|do)\b)({IDENT})\s*:(?!:)')
_TERMINATOR = re.compile(r'(?:break|continue)\s*;|return\b[^;]*;|goto\s+\w+\s*;')
_DECLARATION = re.compile(rf'(?m)^[ \t]*(?:register[ \t]+)?(?P<type>(?:unsigned|signed)[ \t]+(?:char|short|int|long)|long|int|short|char|[su](?:8|16|32))'
                          rf'[ \t]+(?P<name>{IDENT})[ \t]*;[ \t]*$')
_CALL = re.compile(rf'(?<![\w.>])(?!sizeof\b){IDENT}\s*\(')


def _skip(clean, at):
    while at < len(clean) and clean[at].isspace():
        at += 1
    return at


def _statement_end(clean, at, limit):
    """The index just past the statement that starts at `at` (a block, a control statement with its `else`s, or one `;`)."""
    head = re.compile(r'(if|while|for|switch)\s*\(').match(clean, at)
    if head:
        stop = close(clean, head.end() - 1, '(', ')')
        if not stop:
            return limit
        stop = _statement_end(clean, _skip(clean, stop), limit)
        if head[1] == 'if':
            while True:
                other = re.compile(r'\s*else\b').match(clean, stop)
                if not other:
                    break
                stop = _statement_end(clean, _skip(clean, other.end()), limit)
        return stop
    if re.compile(r'do\b').match(clean, at):
        stop = _statement_end(clean, _skip(clean, at + 2), limit)
        tail = re.compile(r'\s*while\s*\(').match(clean, stop)
        if not tail:
            return stop
        stop = close(clean, tail.end() - 1, '(', ')')
        semicolon = clean.find(';', stop, limit) if stop else -1
        return semicolon + 1 if semicolon >= 0 else limit
    if clean[at] == '{':
        return close(clean, at, '{', '}') or limit
    depth = 0
    for index in range(at, limit):
        char = clean[index]
        depth += char in '({['
        depth -= char in ')}]'
        if char == ';' and depth <= 0:
            return index + 1
    return limit


def _items(clean, start, end):
    """[(kind, start, end)] of the top level of clean[start:end]: 'case' and 'label' items and every statement."""
    items, at = [], _skip(clean, start)
    while at < end:
        found = _CASE.match(clean, at)
        if found:
            items.append(('case', at, found.end()))
            at = _skip(clean, found.end())
            continue
        found = _LABEL.match(clean, at)
        if found:
            items.append(('label', at, found.end()))
            at = _skip(clean, found.end())
            continue
        stop = _statement_end(clean, at, end)
        if stop <= at:
            return None
        items.append(('stmt', at, stop))
        at = _skip(clean, stop)
    return items


def _terminates(clean, start, end):
    """Whether the statement clean[start:end] always leaves its arm: `break;`, `return`, `goto`, or a block that ends so."""
    text = clean[start:end].strip()
    if _TERMINATOR.fullmatch(text):
        return True
    wrapped = re.fullmatch(r'(?:do\s*)?(\{.*\})\s*(?:while\s*\(\s*0\s*\)\s*;)?', text, re.S)
    if not wrapped:
        return False
    base = start + clean[start:end].index(wrapped[1])
    inner = [item for item in (_items(clean, base + 1, base + len(wrapped[1]) - 1) or []) if item[0] == 'stmt']
    return bool(inner) and _terminates(clean, inner[-1][1], inner[-1][2])


def _unwrap_goto(text):
    """(statements before it, label) of `goto L;` as a statement or the tail of a one-shot `do { } while (0);`, or None."""
    plain = re.fullmatch(rf'\s*goto\s+({IDENT})\s*;\s*', text)
    if plain:
        return '', plain[1]
    wrapped = re.fullmatch(r'\s*do\s*\{(?P<body>.*)\}\s*while\s*\(\s*0\s*\)\s*;\s*', text, re.S)
    if wrapped:
        tail = re.search(rf'\bgoto\s+({IDENT})\s*;\s*$', wrapped['body'])
        if tail and wrapped['body'].count('goto') == 1 and not re.search(r'\b(?:break|continue)\b', wrapped['body']):
            return wrapped['body'][:tail.start()].strip(), tail[1]
    return None


def _words(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _declared(part):
    out = {}
    for hit in _DECLARATION.finditer(part.clean, part.opening + 1, part.end):
        before = part.clean[part.opening + 1:hit.start()].strip()
        if before and not before.endswith((';', '{', '}')):
            continue
        out[hit['name']] = ' '.join(hit['type'].split())
    return out


def _statements(text):
    """The top-level statements of the C text `text` (blocks and `if` chains whole), as strings."""
    blank = _blank(text)
    return [text[a:b].strip() for kind, a, b in (_items(blank, 0, len(blank)) or []) if kind == 'stmt']


def _split(source, clean, opening, closing):
    items = _items(clean, opening + 1, closing)
    if not items:
        return None
    groups, current = [], []
    for item in items:
        current.append(item)
        if item[0] == 'stmt' and _terminates(clean, item[1], item[2]):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _run(source, clean, groups, labels, label, depth=0):
    """The statements after `label` to the end of its arm (a trailing `goto` followed), or None."""
    if depth > 3 or label not in labels:
        return None
    number, index = labels[label]
    out = []
    for item in groups[number][index + 1:]:
        if item[0] == 'label':
            continue
        if item[0] == 'case':
            return None
        text = source[item[1]:item[2]]
        tail = _unwrap_goto(text)
        if tail is not None:
            more = _run(source, clean, groups, labels, tail[1], depth + 1)
            return None if more is None else out + _statements(tail[0]) + more
        if re.search(r'\bgoto\b', clean[item[1]:item[2]]):
            return None
        out.append(text.strip())
    return out


def _arms(source, clean, groups):
    """[[(kind, text)]] per arm with every `goto` replaced by its run, or None when one cannot be."""
    labels = {}
    for number, group in enumerate(groups):
        for index, item in enumerate(group):
            if item[0] == 'label':
                labels[clean[item[1]:item[2]].rstrip(': \t\n')] = (number, index)
    if not labels:
        return None
    arms, used = [], set()
    for group in groups:
        body = []
        for item in group:
            text = source[item[1]:item[2]].strip()
            if item[0] == 'case':
                body.append(('case', text))
                continue
            if item[0] == 'label':
                continue
            tail = _unwrap_goto(source[item[1]:item[2]])
            if tail is None:
                if re.search(r'\bgoto\b', clean[item[1]:item[2]]):
                    return None
                body.append(('stmt', text))
                continue
            before, label = tail
            run = _run(source, clean, groups, labels, label)
            if run is None:
                return None
            used.add(label)
            if before:
                body += [('stmt', stmt) for stmt in _statements(before)]
            body += [('stmt', stmt) for stmt in run]
        arms.append(body)
    if not used:
        return None
    kept = []
    for body in arms:
        if not any(kind == 'case' for kind, _ in body):
            continue  # an arm only the `goto`s reached
        kept.append(body)
    return kept


def _refs(text, name):
    return len(_words(name).findall(text))


def _scoped(arms, declared, outside):
    """The locals that only the switch's arms use, assigned before any read in each arm that names them, in two or more."""
    found = []
    for name in declared:
        if _words(name).search(outside):
            continue
        users = [body for body in arms if any(_words(name).search(text) for kind, text in body if kind == 'stmt')]
        if len(users) < 2:
            continue
        sound = True
        for body in users:
            for segment in _segments(body):
                first = next((text for text in segment if _words(name).search(text)), None)
                if first is not None and not re.match(rf'{re.escape(name)}\s*=(?!=)', first[_words(name).search(first).start():]):
                    sound = False
        if sound:
            found.append(name)
    return found


def _segments(body):
    """The statement lists between an arm's inner `case` labels."""
    segments, current = [], []
    for kind, text in body:
        if kind == 'case':
            segments.append(current)
            current = []
        else:
            current.append(text)
    segments.append(current)
    return [segment for segment in segments if segment]


def _assigns(text, name):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', text)


def _fold(statements, scoped):
    """`v = 0x2F;` read later in the segment as `v` becomes the literal there, when it is the only assignment of `v`."""
    out = list(statements)
    for name in scoped:
        mine = [i for i, text in enumerate(out) if _words(name).search(text)]
        if not mine:
            continue
        sets = [i for i in mine if _assigns(out[i], name)]
        first = re.fullmatch(rf'\s*{re.escape(name)}\s*=\s*({LITERAL})\s*;\s*', out[sets[0]]) if len(sets) == 1 else None
        if not first or sets[0] != mine[0] or len(mine) < 2:
            continue
        for i in mine[1:]:
            out[i] = _words(name).sub(first[1], out[i])
        out[sets[0]] = ''
    return [text for text in out if text]


def _compound(statements, scoped):
    """`t = w & M; X = t | K;` as `w &= M; w |= K; X = w;` when `t` and `w` are the segment's own scratch locals."""
    out, i = [], 0
    while i < len(statements):
        first = re.fullmatch(rf'\s*({IDENT})\s*=\s*({IDENT})\s*&\s*({LITERAL})\s*;\s*', statements[i])
        if first and i + 1 < len(statements) and first[1] in scoped and first[2] in scoped and first[1] != first[2]:
            second = re.fullmatch(rf'\s*(?P<x>[^;=]+?)\s*=\s*(?:\(\s*s32\s*\)\s*)?\(?\s*{re.escape(first[1])}\s*\|\s*(?P<k>{LITERAL})\s*\)?\s*;\s*',
                                  statements[i + 1])
            rest = ' '.join(statements[i + 2:])
            if second and not _words(first[1]).search(rest) and not _words(first[2]).search(rest) \
                    and not _words(first[1]).search(second['x']) and not _words(first[2]).search(second['x']):
                out += [f'{first[2]} &= {first[3]};', f'{first[2]} |= {second["k"]};', f'{second["x"]} = {first[2]};']
                i += 2
                continue
        out.append(statements[i])
        i += 1
    return out


def _word_updates(statements, fresh):
    """`X = (X & M) | K;` as `w = X; w &= M; w |= K; X = w;` on a new local `w`: ([statements], [new locals])."""
    out, made = [], []
    for text in statements:
        hit = re.fullmatch(r'\s*(?P<x>[^;=]+?)\s*=\s*(?:\(\s*s32\s*\)\s*)?\(\s*\(\s*(?P<y>[^;=&|]+?)\s*&\s*(?P<m>' + LITERAL
                           + r')\s*\)\s*\|\s*(?P<k>' + LITERAL + r')\s*\)\s*;\s*', text)
        if hit and re.sub(r'\s+', '', hit['x']) == re.sub(r'\s+', '', hit['y']) and not _CALL.search(hit['x']):
            word = fresh()
            made.append(word)
            out += [f'{word} = {hit["x"]};', f'{word} &= {hit["m"]};', f'{word} |= {hit["k"]};', f'{hit["x"]} = {word};']
        else:
            out.append(text)
    return out, made


def _mixed(statements, scoped):
    """The statements before a word update's last statement move to just before it (its store), keeping their order."""
    webs = [name for name in scoped if any(_words(name).search(text) for text in statements)]
    keep = [name for name in webs if any(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:&|\|)=', text) for text in statements)]
    if len(keep) != 1:
        return statements
    web = keep[0]
    last = max(i for i, text in enumerate(statements) if _words(web).search(text))
    if not re.fullmatch(rf'\s*[^;=]+=\s*{re.escape(web)}\s*;\s*', statements[last]):
        return statements
    stored = re.match(r'\s*([^;=]+?)\s*=', statements[last])[1]
    movable, stay = [], []
    for i in range(last):
        text = statements[i]
        if _words(web).search(text):
            stay.append(text)
        elif _CALL.search(text) or re.sub(r'\s+', '', stored) in re.sub(r'\s+', '', text) or re.search(r'\b(?:break|return|goto|continue)\b', text):
            return statements
        else:
            movable.append(text)
    after = [text for text in statements[last + 1:]]
    first = min(i for i, text in enumerate(statements) if _words(web).search(text))
    # statements before the web's first statement stay put unless they only precede the update (all of them do here)
    return stay + movable + [statements[last]] + after if first >= 0 else statements


def _arm_statements(body, scoped, mixed, fresh):
    """The arm's items with each segment's statements folded, put in compound form and (mixed) moved; (items, new locals)."""
    out, made, segment = [], [], []

    def flush():
        if not segment:
            return
        statements = list(segment)
        if mixed:
            flat = []
            for text in statements:
                one_shot = re.fullmatch(r'do\s*\{(?P<body>.*)\}\s*while\s*\(\s*0\s*\)\s*;', text, re.S)
                if one_shot and not re.search(r'\b(?:break|continue|goto)\b', one_shot['body']):
                    flat += _statements(one_shot['body'])
                else:
                    flat.append(text)
            statements = flat
        statements = _compound(_fold(statements, scoped), scoped)
        if mixed:
            statements, new = _word_updates(statements, fresh)
            made.extend(new)
            statements = _mixed(statements, scoped + new)
        out.extend(('stmt', text) for text in statements)
        segment.clear()

    for kind, text in body:
        if kind == 'case':
            flush()
            out.append(('case', text))
        else:
            segment.append(text)
    flush()
    return out, made


def _build(source, part, opening, closing, declared, mixed):
    """The text of the switch body (braces included) with every `goto` replaced by its run, or None."""
    clean = part.clean
    groups = _split(source, clean, opening, closing)
    arms = _arms(source, clean, groups) if groups else None
    if arms is None:
        return None
    outside = clean[part.opening + 1:opening] + ' ' + clean[closing:part.end]
    for hit in _DECLARATION.finditer(outside):
        outside = outside[:hit.start()] + ' ' * (hit.end() - hit.start()) + outside[hit.end():]
    scoped = _scoped(arms, declared, outside)
    counter = [0]

    def fresh():
        counter[0] += 1
        return f'word{counter[0]}'

    lines = []
    for body in arms:
        used = [name for name in scoped if any(_words(name).search(text) for kind, text in body if kind == 'stmt')]
        out, made = _arm_statements(body, used, mixed, fresh)
        names = [name for name in used if any(_words(name).search(text) for kind, text in out if kind == 'stmt')]
        declarations = [f'{declared[name].replace("register ", "")} {name};' for name in names] + [f's32 {name};' for name in made]
        while out and out[0][0] == 'case':
            lines.append(f'    {out.pop(0)[1]}')
        if declarations:
            lines += ['    {'] + [f'        {text}' for text in declarations]
        indent = '        ' if declarations else '        '
        lines += [f'    {text}' if kind == 'case' else f'{indent}{text}' for kind, text in out]
        if declarations:
            lines.append('    }')
        lines.append('')
    return '{\n' + '\n'.join(lines) + '\n}'


def variants(source, name):
    """Proposals: the switch's arms with their own copies of the label runs (see the module docstring)."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    declared = _declared(part)
    out = []
    for hit in _SWITCH.finditer(clean, part.opening + 1, part.end):
        head = close(clean, hit.end() - 1, '(', ')')
        block = clean.find('{', head) if head else -1
        if block < 0 or clean[head:block].strip():
            continue
        end = close(clean, block, '{', '}')
        if not end:
            continue
        for mixed, family in ((False, FAMILY), (True, MIXED)):
            body = _build(source, part, block, end - 1, declared, mixed)
            if body is None:
                continue
            text = edit(source, [(block, end, body)])
            out.append((family, text))
            for _, scoped in parameter_test_scope.variants(text, name)[:SCOPE_LIMIT]:
                out.append((SCOPED, scoped))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 97}  # the registry: no caller wiring (registry.py)
