"""A field's read-modify-write written the other ways the game wrote it: through a temporary, with a compound update.

m2c writes a flag-word update as one expression, `p->state = (p->state & ~0xFC) | 0x10;`, and a halfword's `p->flags |= 2;`.
gcc 2.7.2 builds the same loads and ands from either, but the pseudo registers differ: a temporary updated in place
(`w = p->state; w &= ~0xFC; w |= 0x10; p->state = w;`) is one local-alloc quantity (each step's result is tied to its dying
first operand), where the single expression is three, and the quantity's life and reference count rank it against the
neighbouring values. In a 795-instruction N64 object spawner two such updates, one respelled as the compound temporary
and the other left as the game's `p->flags = p->flags | 2;`, took 635 -> 180 once the statements stood in the order that
puts the flag update before the word update (the order was found by a statement-order grid; the spelling alone moved
nothing, 690 -> 690, which is why the family also offers the pair). The reading of local-alloc.c is a hypothesis; the judge
decides.

Spellings offered, for a field `LV` (an lvalue with no side effects: members, indexes, dereferences, casts and macro
calls) read and written in one statement:
  `LV = (LV & M) | K;`      -> `T = LV; T &= M; T |= K; LV = T;`   (T a new local of the field's type)
  `T = LV; T = (T & M) | K; LV = T;` -> `T = LV; T &= M; T |= K; LV = T;`
  `LV |= K;`                -> `LV = LV | K;`
One child per site, one with every site of the function respelled.
"""
import itertools
import re

from .arm_block_support import IDENT, NUMBER, brace_pairs, statements
from .integer_repair_support import edit, view

FAMILY = 'rmw_compound_temp'
FAMILIES = (FAMILY,)

MASK = rf'~?\s*\(?\s*(?:{NUMBER}|~\s*{NUMBER})\s*\)?'
TYPED = re.compile(rf'(?:\*\s*\(\s*(?P<t1>[A-Za-z_][\w ]*?)\s*\*\s*\)|F\([^;]*?,\s*(?P<t2>[A-Za-z_][\w ]*?)\s*,\s*{NUMBER}\s*\))')


def _plain(text):
    if re.search(r'\+\+|--|[^=!<>]=[^=]', text):
        return False
    return all(m[1].isupper() or m[1] == 'F' for m in re.finditer(rf'(?<![\w.>]){IDENT}\s*\(', text)
               for m in [re.match(rf'({IDENT})', m.group().strip())])


def _type(lvalue):
    hit = TYPED.search(lvalue)
    name = ((hit['t1'] or hit['t2']) if hit else '').strip()
    return name if re.fullmatch(r'(?:u|s)(?:8|16|32)', name) else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    sites = []
    for block_open, block_close in sorted(pairs.items()):
        units = statements(clean, block_open + 1, block_close)
        for index, (start, end) in enumerate(units):
            text = clean[start:end].strip()
            hit = re.fullmatch(r'(?P<lv>[^;{}=]+?)\s*=(?!=)\s*\(\s*(?P=lv)\s*&\s*(?P<mask>[^;{}|&]+?)\s*\)\s*\|\s*(?P<k>[^;{}|&]+?)\s*;', text)
            if hit and _plain(hit['lv']) and _type(hit['lv']):
                sites.append(('word', start, end, hit['lv'].strip(), hit['mask'].strip(), hit['k'].strip(), None))
                continue
            hit = re.fullmatch(r'(?P<lv>[^;{}=|]+?)\s*\|=\s*(?P<k>[^;{}]+?)\s*;', text)
            if hit and _plain(hit['lv']) and _type(hit['lv']):
                sites.append(('or', start, end, hit['lv'].strip(), None, hit['k'].strip(), None))
                continue
            if index + 2 < len(units):
                a, b, c = units[index], units[index + 1], units[index + 2]
                ta, tb, tc = (clean[x:y].strip() for x, y in (a, b, c))
                m1 = re.fullmatch(rf'(?P<t>{IDENT})\s*=(?!=)\s*(?P<lv>[^;{{}}]+?)\s*;', ta)
                m2 = re.fullmatch(rf'(?P<t>{IDENT})\s*=(?!=)\s*\(\s*(?P=t)\s*&\s*(?P<mask>[^;{{}}|&]+?)\s*\)\s*\|\s*(?P<k>[^;{{}}|&]+?)\s*;', tb)
                m3 = re.fullmatch(rf'(?P<lv>[^;{{}}=]+?)\s*=(?!=)\s*(?P<t>{IDENT})\s*;', tc)
                if (m1 and m2 and m3 and m1['t'] == m2['t'] == m3['t'] and m1['lv'].strip() == m3['lv'].strip()
                        and _plain(m1['lv'])):
                    sites.append(('temp', b[0], b[1], m1['t'], m2['mask'].strip(), m2['k'].strip(), None))
    out = []
    decl_at = clean.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[decl_at:])[0] or '  '
    names = []
    for number in range(1, len(sites) + 1):
        fresh = f'rmw{number}'
        if re.search(rf'\b{fresh}\b', clean):
            return []
        names.append(fresh)

    def replacement(site, tmp):
        kind, start, end, lv, mask, k, _ = site
        if kind == 'word':
            return (start, end, f'{tmp} = {lv}; {tmp} &= {mask}; {tmp} |= {k}; {lv} = {tmp};', _type(lv))
        if kind == 'or':
            return (start, end, f'{lv} = {lv} | {k};', None)
        return (start, end, f'{lv} &= {mask}; {lv} |= {k};', None)

    # one temporary per site: a name shared by two sites is one pseudo with both lifetimes (370 against 180 on the
    # spawner's two marker blocks, each respelled with its own)
    made = [(site, replacement(site, names[number])) for number, site in enumerate(sites)]
    for number, (site, (start, end, text, type_)) in enumerate(made):
        edits = [(start, end, text)]
        if type_:
            edits.append((decl_at, decl_at, f'{indent}{type_} {names[number]};\n'))
        result = edit(source, edits)
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))
    if len(made) > 1:
        edits = []
        for number, (_, (start, end, text, type_)) in enumerate(made):
            edits.append((start, end, text))
            if type_:
                edits.append((decl_at, decl_at, f'{indent}{type_} {names[number]};\n'))
        result = edit(source, edits)
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))
    # one temporary for several sites, the other way: in a 534-instruction panel builder two of the three flag-word
    # updates (the third's own temporary or the plain expression changed nothing) respelled through ONE shared temporary were
    # 820 -> 660 where a temporary each (the all-sites child above) was 820; the shared name is one pseudo with every site's
    # references, which is what changed the order of the registers around the calls (a hypothesis read from the dumps)
    word = [number for number, (site, _) in enumerate(made) if site[0] == 'word']
    if len(word) > 1:
        shared = names[word[0]]
        subsets = [word] + ([list(pair) for pair in itertools.combinations(word, 2)] if len(word) > 2 else [])
        for subset in subsets:
            types = {made[number][1][3] for number in subset}
            if len(types) != 1:
                continue
            edits = []
            for number in subset:
                _, _, _, lv, mask, k, _ = made[number][0]
                start, end = made[number][1][:2]
                edits.append((start, end, f'{shared} = {lv}; {shared} &= {mask}; {shared} |= {k}; {lv} = {shared};'))
            edits.append((decl_at, decl_at, f'{indent}{types.pop()} {shared};\n'))
            result = edit(source, edits)
            if result != source and (FAMILY, result) not in out:
                out.append((FAMILY, result))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 88}  # the registry: no caller wiring (registry.py)
