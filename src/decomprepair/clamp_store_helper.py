"""A repeated "compute one value from another with branches, then store it" run, written as an inline helper that
takes the destination, and a two-dimensional pointer table read with a constant column, written flat.

A per-frame input handler reads both axes of each pad, cuts a dead zone out of each and stores the result through a
table of pointers:

    x = pads[i]->stick_x;
    if (x > 50) { v = x - 50; } else { v = 0; if (x < -50) { v = x + 50; } }
    *axes.p[i][0] = v;

The target loads the destination pointer *before* the first compare, and computes the second axis's pointer as table
base plus a stepped offset. An SN GCC 2.8.1 build (sn-n64-281, 796 instructions; the numbers are one function's, with
the rest of it already matching) gave:

- the run above written out twice, the table `s32 *p[4][2]`: 1330 with the destination set in a pointer local before
  the branches, 1475 in the store-after form with a flat table;
- a flat table `s32 *p[8]` indexed `i * 2` and `i * 2 + 1`, with the pointer local: 155;
- one `static __inline__ void f(s32 *out, s32 x)` called with `(axes.p[i][0], pads[i]->stick_x)` over the 2D table:
  1310; over the flat table: exact (0).

The helper's arguments are evaluated before its body, which is the target's order. Why a pointer local does not give the
same allocation is not explained here (a hypothesis: the parameter copy makes a pseudo of its own).

clamp_store_helper
    Runs of `[x = SRC;] [p = ADDR;] if (...) {v = ...} else ...; *p = v;` (or a `v = c ? a : b;` statement, or a store
    straight to an lvalue) whose branches only read `x` and literals and only write `v`, where `v` (and `p`, and `x` when
    the run sets it) are plain locals used nowhere else. Each group of identical runs becomes one inline helper; with
    several groups, one child each and one with all of them.
flat_pair_member
    `T *p[A][B];` (a struct member or a local without an initializer) whose every use is `p[i][K]` with a literal `K`,
    declared `T *p[A * B]` and read `p[i * B + K]`.
clamp_store_helper_flat
    Both.
"""
import re

from .csource import _blank
from .pattern_repairs import close

HELPER = 'clamp_store_helper'
FLAT = 'flat_pair_member'
BOTH = 'clamp_store_helper_flat'
FAMILIES = (HELPER, FLAT, BOTH)
GROUPS = 4  # separate helpers offered

IDENT = r'[A-Za-z_]\w*'
TYPE = r'(?:u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|char|short|int|long|float|double|(?:unsigned|signed)(?: (?:char|short|int|long))?)'
_WORD = re.compile(r'\b' + IDENT + r'\b')
_IF = re.compile(r'(?m)^(?P<indent>[ \t]*)if\s*\(')
_TERNARY = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<v>' + IDENT + r')\s*=(?!=)[^;{}]*\?[^;{}]*;')
_SET = re.compile(r'(?<![\w.>])(?P<name>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;{}]+);\s*$')
_STORE = re.compile(r'\s*(?P<lv>[^;{}=]+?)\s*=(?!=)\s*(?P<v>' + IDENT + r')\s*;')
_ELSE = re.compile(r'\s*else\b\s*')
_KEYWORDS = {'if', 'else'}
_CALL = re.compile(r'\b' + IDENT + r'\s*\(')


def _body(source, name):
    """`(clean, line start of the function, its opening brace, the end of its body)`, or None."""
    clean = _blank(source)
    head = re.search(r'(?m)^[A-Za-z_][\w \t\*]*?\b' + re.escape(name) + r'\s*\([^;{]*\)\s*\{', clean)
    if not head:
        return None
    brace = head.end() - 1
    end = close(clean, brace, '{', '}')
    if end is None:
        return None
    return clean, head.start(), brace, end


def _if_end(clean, at):
    """The end of the `if`/`else` chain whose `if` starts at `at`; braced arms only."""
    here = at
    while True:
        paren = clean.find('(', here)
        after = close(clean, paren, '(', ')') if paren >= 0 else None
        if after is None:
            return None
        block = re.compile(r'\s*\{').match(clean, after)
        if not block:
            return None
        end = close(clean, block.end() - 1, '{', '}')
        if end is None:
            return None
        other = _ELSE.match(clean, end)
        if not other:
            return end
        if clean.startswith('if', other.end()):
            here = other.end()
            continue
        if clean[other.end():other.end() + 1] != '{':
            return None
        return close(clean, other.end(), '{', '}')


def _local(text, name):
    """The declared type of the plain scalar local `name` (declared alone on its line), or None."""
    found = re.findall(r'(?m)^[ \t]*(' + TYPE + r')\s+' + re.escape(name) + r'\s*;', text)
    return found[0] if found and len(set(found)) == 1 else None


def _pointee(text, name):
    """T for a plain local `T *name;`, or None."""
    found = re.findall(r'(?m)^[ \t]*(' + TYPE + r')\s*\*\s*' + re.escape(name) + r'\s*;', text)
    return found[0] if found and len(set(found)) == 1 else None


def _stored_type(clean, lv):
    """The scalar type written by the lvalue `lv`, from the one declaration of its last name in the source."""
    bare = lv
    while True:
        shorter = re.sub(r'\[[^\[\]]*\]', '', bare)
        if shorter == bare:
            break
        bare = shorter
    deref = bare.startswith('*')
    path = bare[1:].strip() if deref else bare.strip()
    if not re.fullmatch(IDENT + r'(?:\s*(?:\.|->)\s*' + IDENT + r')*', path):
        return None
    last = _WORD.findall(path)[-1]
    subscripts = lv.count('[')
    declared = re.findall(r'\b(' + TYPE + r')(\s*\*\s*|\s+)' + re.escape(last) + r'((?:\s*\[[^\]\n]*\])*)\s*;', clean)
    kinds = set()
    for kind, star, dims in declared:
        pointer = '*' in star
        # `*p[i]` writes a T through a `T *p[N]`; `t[i]` writes a T of a `T t[N]`; nothing else is resolved
        if deref and pointer and dims.count('[') == subscripts:
            kinds.add(kind)
        elif not deref and not pointer and dims.count('[') == subscripts:
            kinds.add(kind)
        else:
            return None
    return kinds.pop() if len(kinds) == 1 else None


def _pure_value(text, v, x):
    """Whether `text` names only `v`, `x` and keywords, and calls nothing."""
    words = set(_WORD.findall(re.sub(r'\b(?:0[xX][0-9A-Fa-f]+|\d+\.?\d*)[uUlLfF]*', ' ', text)))
    return words <= _KEYWORDS | {v, x} and not re.search(r'\+\+|--|&(?!&)', text)


def _ladder_reads(ladder, v):
    """The one name the ladder reads besides `v`, or None."""
    words = set(_WORD.findall(re.sub(r'\b(?:0[xX][0-9A-Fa-f]+|\d+\.?\d*)[uUlLfF]*', ' ', ladder))) - _KEYWORDS - {v}
    if len(words) != 1:
        return None
    x = words.pop()
    if not _pure_value(ladder, v, x):
        return None
    # every assignment inside writes `v`
    for hit in re.finditer(r'(?<![=!<>+\-*/%&|^])=(?!=)', ladder):
        if not re.search(r'(?<![\w.>])' + re.escape(v) + r'\s*$', ladder[:hit.start()]):
            return None
    return x


def _runs(source, clean, brace, end):
    found = []
    last = brace
    candidates = []
    for hit in _IF.finditer(clean, brace, end):
        stop = _if_end(clean, hit.end('indent'))
        if stop is not None:
            candidates.append((hit.end('indent'), stop, hit['indent'], None))
    for hit in _TERNARY.finditer(clean, brace, end):
        candidates.append((hit.end('indent'), hit.end(), hit['indent'], hit['v']))
    for start, stop, indent, v in sorted(candidates, key=lambda c: c[0]):
        if start < last:
            continue
        store = _STORE.match(clean, stop)
        if not store:
            continue
        ternary = v is not None
        v = store['v']
        ladder = clean[start:stop]
        if not re.search(r'(?<![\w.>])' + re.escape(v) + r'\s*=(?!=)', ladder):
            continue
        if ternary and not ladder.startswith(v):
            continue
        x = _ladder_reads(ladder, v)
        if x is None:
            continue
        lv = source[store.start('lv'):store.end('lv')].strip()
        begin = start
        pointer = source_value = None
        # `p = ADDR;` and `x = SRC;` right before the branches, in either order
        for _ in range(2):
            before = _SET.search(clean, max(brace, begin - 400), begin)
            if not before:
                break
            name = before['name']
            value = source[before.start('value'):before.end('value')].strip()
            if name == x and source_value is None:
                source_value = value
            elif pointer is None and lv == '*' + name:
                pointer = (name, value)
            else:
                break
            begin = before.start('name')
        found.append({'start': begin, 'end': store.end(), 'indent': indent, 'v': v, 'x': x, 'lv': lv,
                      'source': source_value, 'pointer': pointer, 'ladder': source[start:stop]})
        last = store.end()
    return found


def _address(lv):
    if lv.startswith('*'):
        return lv[1:].strip()
    return f'&{lv}'


def _typed(text, clean, run):
    """`run` with its types and call arguments, or None when it can't be moved into a helper."""
    v_type = _local(text, run['v'])
    x_type = _local(text, run['x'])
    if v_type is None or x_type is None:
        return None
    if run['pointer']:
        out_type = _pointee(text, run['pointer'][0])
        address = run['pointer'][1]
    else:
        out_type = _stored_type(clean, run['lv'])
        address = _address(run['lv'])
    if out_type is None:
        return None
    value = run['source'] if run['source'] is not None else run['x']
    names = {run['v'], run['x']} | ({run['pointer'][0]} if run['pointer'] else set())
    for argument in (address, value if run['source'] is not None else ''):
        if _CALL.search(argument) or re.search(r'\+\+|--', argument) or names & set(_WORD.findall(argument)):
            return None
    return dict(run, v_type=v_type, x_type=x_type, out_type=out_type, address=address, value=value)


def _only_in_runs(clean, brace, end, name, runs):
    """Whether every occurrence of `name` in the body is its declaration or inside one of `runs`."""
    declared = re.compile(r'(?m)^[ \t]*' + TYPE + r'(?:\s+|\s*\*\s*)' + re.escape(name) + r'\s*;')
    spans = [(r['start'], r['end']) for r in runs] + [m.span() for m in declared.finditer(clean, brace, end)]
    for hit in re.finditer(r'(?<![\w.])(?<!->)' + re.escape(name) + r'\b', clean[:end]):
        if hit.start() < brace:
            continue
        if not any(a <= hit.start() < b for a, b in spans):
            return False
    return True


def _key(run):
    return (re.sub(r'\s+', '', run['ladder']), run['v'], run['x'], run['v_type'], run['x_type'], run['out_type'])


def _helper(name, number, run):
    out = f'{name}_clampStore{number}'
    lines = run['ladder'].split('\n')
    rest = [line[len(run['indent']):] if line.startswith(run['indent']) else line.lstrip() for line in lines[1:]]
    body = '\n'.join('    ' + line for line in [lines[0]] + rest)
    text = (f'static __inline__ void {out}({run["out_type"]} *out, {run["x_type"]} {run["x"]}) {{\n'
            f'    {run["v_type"]} {run["v"]};\n\n{body}\n    *out = {run["v"]};\n}}\n\n')
    return out, text


def _apply(source, name, at, groups):
    edits, helpers = [], ''
    for number, group in enumerate(groups):
        out, text = _helper(name, number or '', group[0])
        helpers += text
        for run in group:
            edits.append((run['start'], run['end'], f'{out}({run["address"]}, {run["value"]});'))
    new = source
    for start, stop, text in sorted(edits, reverse=True):
        new = new[:start] + text + new[stop:]
    # the locals the runs no longer leave anything to read
    names = {r['v'] for g in groups for r in g} | {r['x'] for g in groups for r in g}
    names |= {r['pointer'][0] for g in groups for r in g if r['pointer']}
    head = new[:at]
    body = new[at:]
    for local in sorted(names):
        if len(re.findall(r'(?<![\w.])(?<!->)' + re.escape(local) + r'\b', _blank(body))) == 1:
            body = re.sub(r'(?m)^[ \t]*' + TYPE + r'(?:\s+|\s*\*\s*)' + re.escape(local) + r'\s*;\n', '', body, count=1)
    return head + helpers + body


def _helper_children(source, name):
    found = _body(source, name)
    if not found:
        return []
    clean, at, brace, end = found
    runs = [t for t in (_typed(source, clean, r) for r in _runs(source, clean, brace, end)) if t]
    groups = {}
    for run in runs:
        groups.setdefault(_key(run), []).append(run)
    usable = []
    for group in groups.values():
        names = {group[0]['v']}
        if any(r['source'] is not None for r in group):
            if not all(r['source'] is not None for r in group):
                continue
            names.add(group[0]['x'])
        names |= {r['pointer'][0] for r in group if r['pointer']}
        # another group's runs may use the same locals: those occurrences are inside runs too
        if all(_only_in_runs(clean, brace, end, local, runs) for local in names):
            usable.append(group)
    usable = usable[:GROUPS]
    if len(usable) > 1:
        # a local shared between groups only goes when every group moves, so each child must stand alone
        return [_apply(source, name, at, [group]) for group in usable] + [_apply(source, name, at, usable)]
    return [_apply(source, name, at, usable)] if usable else []


_PAIR = re.compile(r'(?m)^[ \t]*(?!return\b)(?:' + TYPE + r'|' + IDENT + r')\s*\*\s*(?P<name>' + IDENT +
                   r')\s*\[(?P<a>\d+)\]\s*\[(?P<b>\d+)\]\s*;|\{\s*(?:' + TYPE + r')\s*\*\s*(?P<name2>' + IDENT +
                   r')\s*\[(?P<a2>\d+)\]\s*\[(?P<b2>\d+)\]\s*;')


def _flat(source):
    clean = _blank(source)
    for declared in _PAIR.finditer(clean):
        key = 'name' if declared['name'] else 'name2'
        pair = declared[key]
        suffix = '' if key == 'name' else '2'
        rows, columns = int(declared['a' + suffix]), int(declared['b' + suffix])
        if columns < 2:
            continue
        edits, bad = [], False
        for hit in re.finditer(r'\b' + pair + r'\b', clean):
            if hit.start() == declared.start(key):
                continue
            first = re.compile(r'\s*\[').match(clean, hit.end())
            stop = close(clean, first.end() - 1, '[', ']') if first else None
            second = re.compile(r'\s*\[\s*(\d+)\s*\]').match(clean, stop) if stop is not None else None
            if not second or int(second[1]) >= columns:
                bad = True
                break
            row = source[first.end():stop - 1].strip()
            column = int(second[1])
            if row.isdigit():
                index = str(int(row) * columns + column)
            else:
                if not re.fullmatch(IDENT + r'(?:(?:\.|->)' + IDENT + r')*', row):
                    row = f'({row})'
                index = f'{row} * {columns}' + (f' + {column}' if column else '')
            edits.append((first.end() - 1, second.end(), f'[{index}]'))
        if bad or not edits:
            continue
        a_start = declared.start('a' + suffix) - 1
        b_end = declared.end('b' + suffix) + 1
        edits.append((a_start, b_end, f'[{rows * columns}]'))
        new = source
        for start, end, text in sorted(edits, reverse=True):
            new = new[:start] + text + new[end:]
        return new
    return None


def variants(source, name):
    """`[(family, source)]`."""
    out = [(HELPER, child) for child in _helper_children(source, name)]
    flat = _flat(source)
    if flat is not None:
        both = _helper_children(flat, name)
        if both:
            out.append((BOTH, both[-1]))
        out.append((FLAT, flat))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
