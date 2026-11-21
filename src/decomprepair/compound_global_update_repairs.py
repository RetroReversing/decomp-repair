"""A global updated through m2c's temporary, written as the compound assignment it was.

m2c spells `v = G -= x;` as three statements, `t = G - x; v = t; G = t;` (a rewrite may leave them as `register`
declarations, which are new variables). gcc keeps `t` and `v` apart and stores a copy; the game computed once and
copied the result (`subu $v0`, `move $v1, $v0`, `sw $v0`). An N64 function was 94.5% so and exact as
`v = G -= x;` or `G -= x; v = G;`.

`split_read_modify_write` undoes the other way a byte flag update gets spelled: a load into a local, the update of
the local, and the store back, interleaved with a neighbouring update (`a = *m; b = G; a |= 1; b |= 1; *m = a;
G = b;`). gcc 2.7.2 schedules the two loads, the two `ori`s and the two stores the same way either way, but the extra
local changes which pseudo the scheduler's ties pick first, and with it where the address of `*m` lands among the
case's set-up (`lui/addiu $a2` before or after `lui/addiu $s0`). A KMC gcc 2.7.2 switch case was exact only as
`*m |= 1; G |= 1;`, and another case of it only with the load folded into the update (`a = (*m | 4) & ~1;`) while
the store stayed. Each site is offered folded (load into the update) and collapsed (load, update and store as one
`L op= k;` at the store), and all sites together, since one case alone moved nothing.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compound_global_update'
SPLIT = 'split_read_modify_write'
FAMILIES = (FAMILY, SPLIT)

I = r'[A-Za-z_]\w*'
SHAPE = re.compile(r'(?m)^(?P<ind>[ \t]*)(?:register\s+)?(?P<t>' + I + r')\s*=\s*(?P<g>' + I + r')\s*(?P<op>[-+|&^])\s*(?P<x>[^;\n]+);[ \t]*\n'
                   r'(?:[ \t]*(?:register\s+)?(?P<v>' + I + r')\s*=\s*(?P=t)\s*;[ \t]*\n)?'
                   r'[ \t]*(?P=g)\s*=\s*(?P=t)\s*;[ \t]*\n')


def variants(source, name):
    return _compound(source, name) + split_variants(source, name)


def _compound(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        t, g, op, v, ind = hit['t'], hit['g'], hit['op'], hit['v'], hit['ind']
        x = source[hit.start('x'):hit.end('x')].strip()
        rest = clean[hit.end():end]
        if re.search(r'\b' + t + r'\b', rest) or re.search(r'\b' + t + r'\b', x):
            continue
        forms = [f'{ind}{v} = {g} {op}= {x};\n', f'{ind}{g} {op}= {x};\n{ind}{v} = {g};\n'] if v else [f'{ind}{g} {op}= {x};\n']
        for form in forms:
            text = source[:hit.start()] + form + source[hit.end():]
            result.append((FAMILY, text))
    return result[:4]


STATEMENT = re.compile(r'^(?P<ind>[ \t]*)(?P<lhs>[^;=\n{}]+?)\s*(?P<op>[-+|&^*/]|<<|>>)?=(?!=)\s*(?P<rhs>[^;\n{}]+);[ \t]*$')
CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')
LIMIT = 12


def _word(name):
    return re.compile(r'(?<![\w.])(?<!->)' + re.escape(name) + r'\b')


def _statement(line):
    """A plain assignment line without a call: (indent, lhs, op, rhs), else None."""
    hit = STATEMENT.match(line)
    if not hit or CALL.search(hit['rhs']) or CALL.search(hit['lhs']):
        return None
    return hit['ind'], hit['lhs'].strip(), hit['op'], hit['rhs'].strip()


def _wrap(text):
    return text if re.fullmatch(r'\*?[\w.]+(?:->\w+)*', text) else f'({text})'


def _sites(lines, start, end):
    """Each `t = L; ...; t = f(t); ...; L = t;` run inside one block of lines[start:end]."""
    sites = []
    for i in range(start, end):
        load = _statement(lines[i])
        if not load or load[2] or not re.fullmatch(r'[A-Za-z_]\w*', load[1]):
            continue
        ind, t, _, value = load
        word = _word(t)
        if word.search(value) or not re.search(r'[A-Za-z_]', value):
            continue
        update = store = None
        j = i + 1
        while j < end:
            line = lines[j]
            if line.strip() == '':
                j += 1
                continue
            st = _statement(line)
            if not st or st[0] != ind:
                break
            if word.search(line):
                if update is None:
                    if st[1] == t and (st[2] or word.search(st[3])) and len(word.findall(st[3])) <= 1:
                        update = j
                        j += 1
                        continue
                elif st[1] == value and not st[2] and st[3] == t:
                    store = j
                break
            if st[1] == value or st[1] == t:
                break
            j += 1
        if update is None:
            continue
        if store is not None:
            rest = '\n'.join(lines[store + 1:end])
            later = word.search(rest)
            if later and not re.match(r'\s*=(?!=)', rest[later.end():]):
                store = None
        sites.append((i, update, store, t, value))
    return sites


def _folded(update_line, t, value):
    ind, _, op, rhs = _statement(update_line)
    if op:
        return f'{ind}{t} = {_wrap(value)} {op} {rhs};'
    return f'{ind}{t} = ' + _word(t).sub(lambda m: _wrap(value), rhs, count=1) + ';'


def _collapsed(update_line, store_line, t, value):
    ind, _, op, rhs = _statement(update_line)
    sind = _statement(store_line)[0]
    if op:
        return f'{sind}{value} {op}= {rhs};'
    return f'{sind}{value} = ' + _word(t).sub(lambda m: _wrap(value), rhs, count=1) + ';'


def _apply(lines, edits):
    out = list(lines)
    for index, text in sorted(edits.items(), reverse=True):
        if text is None:
            del out[index]
        else:
            out[index] = text
    return out


def split_variants(source, name):
    """`t = L; t op= k; L = t;` (interleaved with other plain updates) folded and collapsed, alone and together."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    head, body, tail = source[:opening + 1], source[opening + 1:end], source[end:]
    if body.count('\n') != _blank(body).count('\n'):
        return []
    lines = body.split('\n')
    sites = _sites(lines, 0, len(lines))
    if not sites:
        return []
    groups = []  # sites whose lines interleave are one update written twice: offer them together
    for site in sites:
        last = site[2] if site[2] is not None else site[1]
        if groups and site[0] < groups[-1][0]:
            groups[-1][0] = max(groups[-1][0], last)
            groups[-1][1].append(site)
        else:
            groups.append([last, [site]])
    singles, folded_all, collapsed_all = [], {}, {}
    grouped = []
    for _, members in groups:
        folded_group, collapsed_group = {}, {}
        for load, update, store, t, value in members:
            fold = {load: None, update: _folded(lines[update], t, value)}
            singles.append(fold)
            folded_group.update(fold)
            if store is not None:
                whole = {load: None, update: None, store: _collapsed(lines[update], lines[store], t, value)}
                singles.append(whole)
                collapsed_group.update(whole)
            else:
                collapsed_group.update(fold)
        if len(members) > 1:
            grouped += [collapsed_group, folded_group]
        folded_all.update(folded_group)
        collapsed_all.update(collapsed_group)
    edits = ([collapsed_all, folded_all] if len(sites) > 1 else []) + grouped + singles
    result, seen = [], set()
    for edit in edits:
        text = head + '\n'.join(_apply(lines, edit)) + tail
        if text != source and text not in seen:
            seen.add(text)
            result.append((SPLIT, text))
    return result[:LIMIT]
