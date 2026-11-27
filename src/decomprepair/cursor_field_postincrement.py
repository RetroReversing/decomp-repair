"""A stream cursor kept in a field, read through a saved old value, written back as `*field++`.

m2c spells `b = *obj->cursor++;` as three statements, with unrelated stores between them when the scheduler had moved
the load of the cursor apart from the load through it:

    p = M2C_FIELD(obj, u8 **, 0x34);                      M2C_FIELD(obj, f32 *, 0x70) = rate;
    M2C_FIELD(obj, u8 **, 0x34) = (u8 *) (p + 1);   ->    b = *M2C_FIELD(obj, u8 **, 0x34)++;
    M2C_FIELD(obj, f32 *, 0x70) = rate;
    b = *p;

The named old value is a pseudo of its own that lives from the first load to the read; `*field++` loads, steps and
reads in one expression, which gives other registers and another load order. One such site rewritten alone usually
scores worse than the draft, because the function's other sites still hold the old values (250 -> 470 and 815 on a
69-instruction N64 audio sequence reader, KMC GCC 2.7.2, with three sites), so every site is rewritten in one child.
With the other order of two earlier statements (`statement_slide`) and the search's identity inline and byte copy
stripped (`scaffold_strip`, offered here as the combined child) the three-site child was exact.

A site is rewritten only where the load, the step and the one read lie in one block and the statements between them
call nothing, branch nowhere, mention neither the old value nor the cursor, and store only to locals or to other
offsets (or members) of the cursor's own base. The old value may have no other use in the function. A second local that only
carries the load (`q = field; p = q;`) goes with it. The exact judge decides.
"""
import re

from . import scaffold_strip
from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'cursor_field_postincrement'
COMBINED = 'cursor_field_postincrement_strip'
FAMILIES = (FAMILY, COMBINED)
LIMIT = 6

ASSIGN = re.compile(r'(?P<lhs>[^=;]+?)\s*(?<![-+*/%&|^<>!=])=(?!=)\s*(?P<rhs>[^;]+)', re.S)
FIELD = re.compile(rf'\(?\s*\*\s*\(\s*[\w\s]+\*+\s*\)\s*\(\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*(?P<base>{IDENT})\s*\+\s*'
                   rf'(?P<offset>{NUMBER})\s*\)\s*\)?\Z')
MACRO = re.compile(rf'M2C_FIELD\s*\(\s*(?P<base>{IDENT})\s*,[^,()]*,\s*(?P<offset>{NUMBER})\s*\)\Z')
MEMBER = re.compile(rf'(?P<base>{IDENT})\s*->\s*(?P<member>{IDENT})\Z')
BYTE_POINTEE = ('u8', 's8', 'char', 'unsigned char', 'signed char')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _unwrapped(text):
    """The expression without parentheses around the whole of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _place(text):
    """(base, offset or member) of a field of a record named through one pointer, or None."""
    member = MEMBER.match(_unwrapped(text))
    if member:
        return member['base'], member['member']
    found = FIELD.match(text.strip()) or MACRO.match(_unwrapped(text))
    return (found['base'], int(found['offset'].rstrip('uUlL'), 0)) if found else None


def _statements(clean, opening, end):
    """Every simple statement as (block, start, stop), in source order: `block` is the brace it lies in directly, stop is
    past its `;`. A compound statement is left out of its block's list; its own blocks are listed for themselves."""
    found = []
    for block, closing in (brace_pairs(clean, opening, end) or {}).items():
        found += [(block, start, stop) for start, stop in statements(clean, block + 1, closing)
                  if clean[stop - 1] == ';' and '{' not in clean[start:stop]]
    return sorted(found, key=lambda item: item[1])


def _assignment(text):
    found = ASSIGN.fullmatch(text.rstrip(';').strip())
    return (found['lhs'].strip(), found['rhs'].strip()) if found else None


def _harmless(text, old, field, cursor, locals_):
    """A statement the cursor's step may move past."""
    parts = _assignment(text)
    if not parts or re.search(rf'\b{re.escape(old)}\b', text) or _squash(field) in _squash(text):
        return False
    lhs, rhs = parts
    if re.search(rf'(?<!M2C_FIELD)\b(?!sizeof\b){IDENT}\s*\((?!\s*\*)', _casts_dropped(rhs)) or '++' in text or '--' in text:
        return False
    if lhs in locals_:
        return not (cursor and lhs == cursor[0])
    place = _place(lhs)
    return bool(cursor and place and place[0] == cursor[0] and type(place[1]) is type(cursor[1]) and place[1] != cursor[1])


def _casts_dropped(text):
    return re.sub(r'\(\s*(?:[us](?:8|16|32|64)|f32|f64|int|char|short|long|float|double|void)\s*\**\s*\)', ' ', text)


def _pointer_locals(clean, opening, end):
    return {m['name']: re.sub(r'\s+', ' ', m['type'])
            for m in re.finditer(rf'(?<=[;{{}}])\s*(?P<type>(?:unsigned\s+|signed\s+)?{IDENT})\s*\*\s*'
                                 rf'(?P<name>{IDENT})\s*;', clean[opening:end])}


def _scalar_locals(clean, opening, end):
    return set(re.findall(rf'(?<=[;{{}}])\s*(?:(?:unsigned|signed)\s+)?{IDENT}[\s*]+({IDENT})\s*;', clean[opening:end]))


def _typed_field(field, pointee):
    """The cursor spelled so that `++` steps one element of the old value's type, or None when that is not known."""
    cast = re.match(rf'(M2C_FIELD\s*\(\s*{IDENT}\s*,\s*|\(?\s*\*\s*\(\s*)(?P<type>[\w\s]+?)\s*(?P<stars>\*+)', field)
    if not cast:
        return None
    if cast['stars'] != '**' or (cast['type'] != pointee and pointee not in BYTE_POINTEE):
        return None
    return field[:cast.start('type')] + pointee + ' ' + field[cast.end('stars') - 2:]


def _sites(source, part, name):
    clean, opening, end = part.clean, part.opening, part.end
    pointers = _pointer_locals(clean, opening, end)
    locals_ = _scalar_locals(clean, opening, end)
    statements = _statements(clean, opening, end)
    texts = [source[start:stop] for _, start, stop in statements]
    parts = [_assignment(clean[start:stop]) for _, start, stop in statements]
    sites = []
    for step_at, step in enumerate(parts):
        if not step:
            continue
        field, value = step
        stepped = re.fullmatch(rf'(?:\(\s*[\w\s]+\*+\s*\)\s*)?\(?\s*(?P<old>{IDENT})\s*\+\s*1\s*\)?', value)
        if not stepped or stepped['old'] not in pointers:
            continue
        old, block = stepped['old'], statements[step_at][0]
        run = [i for i, s in enumerate(statements) if s[0] == block]
        before = [i for i in run if i < step_at]
        load_at = next((i for i in reversed(before) if parts[i] and parts[i][0] == old), None)
        if load_at is None:
            continue
        dropped, loaded = [load_at], parts[load_at][1]
        carrier = None
        if loaded in pointers:
            # `q = field; p = q;`: the second local only carries the load
            carrier = loaded
            previous = before.index(load_at) - 1
            if previous < 0 or not parts[before[previous]] or parts[before[previous]][0] != carrier:
                continue
            load_at = before[previous]
            dropped, loaded = [load_at, dropped[0]], parts[load_at][1]
        if _squash(_unwrapped(loaded)) != _squash(_unwrapped(field)):
            continue
        reads = [i for i in run if i > step_at and re.search(rf'\b{old}\b', clean[statements[i][1]:statements[i][2]])]
        if not reads:
            continue
        read_at = reads[0]
        read_text = clean[statements[read_at][1]:statements[read_at][2]]
        uses = list(re.finditer(rf'\*\s*{old}\b(?!\s*(?:\[|\(|\.|->|\+\+|--))', read_text))
        if (len(uses) != 1 or len(re.findall(rf'\b{old}\b', read_text)) != 1 or re.search(r'&&|\|\||\?', read_text)
                or not _assignment(read_text) or _squash(field) in _squash(read_text)):
            continue
        # every statement in the window lies in this block: a brace between them would end the straight run
        if re.search(r'[{}:]', clean[statements[load_at][1]:statements[read_at][2]]):
            continue
        cursor = _place(field)
        window = [i for i in range(load_at, read_at) if i != step_at and i not in dropped]
        if not all(_harmless(clean[statements[i][1]:statements[i][2]], old, field, cursor, locals_) for i in window):
            continue
        original = texts[step_at][:texts[step_at].rfind('=')].strip()
        spelled = _typed_field(original, pointers[old]) or (original if value.startswith(old) else None)
        if not spelled:
            continue
        place = _unwrapped(spelled)
        place = place if re.fullmatch(rf'(?:M2C_FIELD\s*\(.*\)|{IDENT}(?:(?:->|\.){IDENT})*)', place, re.S) else f'({place})'
        at = statements[read_at][1] + uses[0].start()
        spans = [statements[i][1:] for i in dropped + [step_at]]
        names = {old: len(spans) + 1}
        sites.append({'drop': spans, 'use': (at, at + len(uses[0][0]), f'*{place}++'), 'old': old, 'carrier': carrier,
                      'names': names})
    return sites


def _drop_line(source, start, stop):
    line = source.rfind('\n', 0, start) + 1
    following = source.find('\n', stop)
    if not source[line:start].strip() and following >= 0 and not source[stop:following].strip():
        return line, following + 1, ''
    return start, stop, ''


def _rewrite(source, name, sites):
    """The source with the chosen sites written out, or None when an old value or a carrier is used elsewhere too."""
    part = view(source, name)
    edits = []
    for site in sites:
        edits += [_drop_line(source, *span) for span in site['drop']]
        edits.append(site['use'])
    if len({(a, b) for a, b, _ in edits}) != len(edits):
        return None
    text = edit(source, edits)
    dead = {n for site in sites for n in (site['old'], site['carrier']) if n}
    for local in dead:
        part = view(text, name)
        mentions = list(re.finditer(rf'\b{local}\b', part.clean[part.opening:part.end]))
        if len(mentions) != 1 or _address_taken(part.body, local):
            return None
        declared = re.compile(rf'(?:(?:unsigned|signed)\s+)?{IDENT}\s*\*\s*{local}\s*;')
        found = next((m for m in declared.finditer(part.clean, part.opening, part.end)), None)
        if not found:
            return None
        text = edit(text, [_drop_line(text, found.start(), found.end())])
    return text


def _folded(source, name):
    """[the source with every site written out], then one per old value when there are several."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|volatile)\b', part.body):
        return []
    sites = _sites(source, part, name)
    if not sites:
        return []
    # sites that share an old value go together
    groups = {}
    for site in sites:
        groups.setdefault(site['old'], []).append(site)
    choices = [sites] + (list(groups.values()) if len(groups) > 1 else [])
    results = []
    for chosen in choices[:LIMIT]:
        text = _rewrite(source, name, chosen)
        if text and text not in results:
            results.append(text)
    return results


def variants(source, name, header=''):
    results = [(FAMILY, text) for text in _folded(source, name)]
    # a search's union or identity inline can hide a site: strip first, rewrite, strip what the rewrite freed
    stripped = scaffold_strip.strip(source, name, header)
    for base in ([stripped] if stripped else []) + [text for _, text in results[:1]]:
        folded = _folded(base, name)[:1] if base == stripped else [base]
        for text in folded:
            combined = scaffold_strip.strip(text, name, header) or text
            if combined != source and all(combined != other for _, other in results):
                results.append((COMBINED, combined))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 71}
