"""A byte of flag bits updated step by step, the way m2c spells it, and the way the game's compound updates were written.

Three m2c-era shapes that KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) allocates and schedules differently from the
source the game was built from. They were found together on a 214-instruction slot-update loop that scored 375 and
went 375 -> 330 -> 320 -> 240 -> 230 by these edits (docs/learnings/function/flag-byte-chain-compound.md):

- `guarded_or_compound`: `v = p[i].f; if (c) v |= K; ...; p[i].f = v;` against `p[i].f |= c ? K : 0;`. The temporary and
  the separate store make the store's address a second computation after the guard's join (the load's address pseudo is
  not live across the join, so cse cannot reuse it); the compound update expands the address once, before the load, and
  the store reuses it (320 -> 240: eleven differing rows). The statements between the guard and the store (here a
  never-taken flag test) may only touch other scalars, so moving the store above them cannot change what they read.
- `cast_read_narrow`: a word local that is only ever assigned a byte or halfword value and is read as `(u16) x` somewhere
  is the `u16` the game declared (330 -> 320). The word keeps no `andi` after the merge of its sets, the halfword does.
- `dead_scratch_web_split`: a scratch name reused for one more short value at the end of the function (`s1 = (v >> 2) & 1;
  t = s1 ^ ...;` with `s1` unused after) written with a local of its own (240 -> 230). Reusing the name ties this web to
  the long-lived one's pseudo; a hypothesis for why it matters: the merged webs weight its priority and so its register,
  which local-alloc/global.c decide, not confirmed in the compiler source.

`byte_flag_chain` offers all of them at once as one child, since the three edits were each measured on the same
function and none of them undoes another.
"""
import re

from .integer_repair_support import DECL, IDENT, INTEGER, NUMBER, edit, view

FAMILY_OR = 'guarded_or_compound'
FAMILY_NARROW = 'cast_read_narrow'
FAMILY_WEB = 'dead_scratch_web_split'
FAMILY_ALL = 'byte_flag_chain'
FAMILIES = (FAMILY_OR, FAMILY_NARROW, FAMILY_WEB, FAMILY_ALL)
WORDS = ('int', 's32', 'u32', 'signed int', 'unsigned int', 's16', 'long')
CASTS = re.compile(r'\(\s*(?:unsigned\s+long\s+long|unsigned\s+long|unsigned\s+int|unsigned|long\s+long|long|int|u64|s64|u32|s32)\s*\)')
CHUNK = re.compile(r'\s*(?:(?:if\s*\([^;{}]*\)|else)\s*)*[^;{}]*;')
KEYWORDS = {'if', 'else', 'return', 'goto', 'while', 'for', 'do', 'switch', 'case', 'sizeof'}


def _norm(text):
    return re.sub(r'\s+', '', CASTS.sub('', text))


def _idents(text):
    """The names a lvalue is made of (not the fields after a dot or an arrow)."""
    return set(re.findall(rf'(?<![\w.>]){IDENT}', text)) - KEYWORDS


def _mentions(clean, name, start, end):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end])]


def _plain_assignment(clean, name, at, end):
    """The end of `name = value;` at `at` when it does not read `name` and starts a statement, else None."""
    match = re.compile(rf'{re.escape(name)}\s*=(?!=)\s*(?P<value>[^;{{}}]*);').match(clean, at, end)
    if not match or re.search(rf'(?<![\w.>]){re.escape(name)}\b', match['value']):
        return None
    before = clean[:at].rstrip()
    return match.end() if before[-1:] in (';', '{', '}') else None


def _or_compound(source, part):
    """[(start, end, text)] for each `v = lv; if (c) v |= K; ...; lv = v;` of the function, or []."""
    clean, body_end = part.clean, part.end
    edits = []
    head = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=(?!=)\s*(?P<lv>[^;{{}}=]+?);\s*if\s*\((?P<c>[^;{{}}]+?)\)\s*(?:{{\s*)?'
                      rf'(?P=v)\s*\|=\s*(?P<k>{NUMBER})\s*;\s*(?:}}\s*)?')
    position = part.opening
    while True:
        found = head.search(clean, position, body_end)
        if not found:
            break
        position = found.end()
        v, lv = found['v'], found['lv'].strip()
        if not re.search(r'[\[.>*]', lv) or '(' in re.sub(CASTS, '', lv) or v in _idents(lv):
            continue
        banned = _idents(lv) | {v}
        at, chunks = found.end(), 0
        store = re.compile(rf'\s*(?P<lv2>[^;{{}}=]+?)\s*=\s*{re.escape(v)}\s*;')
        while chunks < 6:
            done = store.match(clean, at, body_end)
            if done and _norm(done['lv2']) == _norm(lv):
                break
            chunk = CHUNK.match(clean, at, body_end)
            text = chunk and chunk.group(0)
            if (not chunk or _idents(text) & banned or re.search(r'[\[*]|->|\.\s*\w|\bgoto\b|\breturn\b|\w:', text)
                    or re.search(rf'(?<![\w.>])(?!if\b)({IDENT})\s*\(', text)):
                done = None
                break
            at, chunks = chunk.end(), chunks + 1
        else:
            done = None
        if not done:
            continue
        after = _mentions(clean, v, done.end(), body_end)
        before = [m for m in _mentions(clean, v, part.opening, found.start())
                  if not re.search(rf'\b(?:{INTEGER})\s+$', clean[:part.opening + m.start()])]
        for first, base, limit in ((after[:1], done.end(), body_end), (before[:1], part.opening, found.start())):
            if first and not _plain_assignment(clean, v, base + first[0].start(), limit):
                break
        else:
            condition = found['c'].strip()
            if not re.fullmatch(IDENT, condition):
                condition = f'({condition})'
            middle = source[found.end():done.start()].strip('\n')
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, found.start()) + 1:]).group()
            middle = indent + middle.lstrip() if middle.strip() else ''
            text = f'{lv} |= {condition} ? {found["k"]} : 0;' + (f'\n{middle}' if middle else '')
            edits.append((found.start(), done.end(), text))
            position = done.end()
    return edits


def _member_types(text):
    types = {}
    for match in re.finditer(rf'\b(?P<type>unsigned\s+(?:char|short)|signed\s+(?:char|short)|[su](?:8|16|32)|char|short|int)\s+(?P<name>{IDENT})\s*(?:\[[^\]]*\])?\s*;', text):
        types.setdefault(match['name'], set()).add(re.sub(r'\s+', ' ', match['type']))
    return types


def _narrow(source, part, header):
    """[(start, end, text)] declaring a word local `u16` when it is read as `(u16) x` and only ever holds a byte or a halfword."""
    context = header + '\n' + source
    if not re.search(r'\bu16\b', context):
        return []
    members = _member_types(context)
    unsigned_small = {'u8', 'u16', 'unsigned char', 'unsigned short'}
    clean, edits = part.clean, []
    for decl in DECL.finditer(clean, part.opening, part.end):
        name = decl['name']
        if re.sub(r'\s+', ' ', decl['type']) not in WORDS:
            continue
        body = clean[part.opening:part.end]
        if not re.search(rf'\(\s*u16\s*\)\s*{re.escape(name)}\b', body) or re.search(rf'&\s*{re.escape(name)}\b', body):
            continue
        sets = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*(?P<op>[-+*/|&^]|<<|>>)?=(?!=)\s*(?P<value>[^;{{}}]*);', body)]
        if not sets or re.search(rf'(?<![\w.>])(?:\+\+|--)\s*{re.escape(name)}\b|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', body):
            continue
        fits = True
        for item in sets:
            value = item['value'].strip()
            number = re.fullmatch(NUMBER, value)
            field = re.search(rf'(?:\.|->)\s*({IDENT})\s*$', value)
            fits = fits and not item['op'] and bool(
                (number and int(re.sub(r'[uUlL]+$', '', value), 0) <= 0xFFFF)
                or re.fullmatch(rf'\(\s*(?:u8|u16)\s*\)[^;]*', value)
                or (field and members.get(field.group(1)) and members[field.group(1)] <= unsigned_small))
        if fits:
            edits.append((decl.start('type'), decl.end('type'), 'u16'))
    return edits


def _split_webs(source, part):
    """[[(start, end, text)]], one edit list per scratch web given a local of its own."""
    clean = part.clean
    declared = {m['name']: m for m in DECL.finditer(clean, part.opening, part.end)}
    found = []
    for name, decl in declared.items():
        mentions = [m for m in _mentions(clean, name, part.opening, part.end) if part.opening + m.start() != decl.start('name')]
        if len(mentions) < 4 or not _plain_assignment(clean, name, part.opening + mentions[0].start(), part.end):
            continue
        for item in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*(?P<value>[^;{{}}]*);', clean[part.opening:part.end]):
            first = part.opening + item.start()
            if re.search(rf'(?<![\w.>]){re.escape(name)}\b', item['value']) or clean[:first].rstrip()[-1:] not in (';', '{', '}'):
                continue
            stop, uses = part.opening + item.end(), []
            while True:
                chunk = re.compile(r'\s*[^;{}]*;').match(clean, stop, part.end)
                if not chunk or not re.search(rf'(?<![\w.>]){re.escape(name)}\b', chunk.group(0)) or re.match(r'\s*(?:if|else|while|for|do)\b', chunk.group(0)):
                    break
                uses.append((stop, chunk.end()))
                stop = chunk.end()
            if not uses or _mentions(clean, name, stop, part.end):
                continue
            found.append((name, decl, (first, part.opening + item.end()), uses))
    results, taken = [], set()
    for name, decl, assignment, uses in found:
        fresh, number = f'{name}_web', 1
        while re.search(rf'\b{fresh}\b', source) or fresh in taken:
            fresh, number = f'{name}_web{number}', number + 1
        taken.add(fresh)
        edits = [(decl.end(), decl.end(), f'\n  {decl["type"]} {fresh};')]
        for lo, hi in [assignment] + uses:
            for mention in _mentions(clean, name, lo, hi):
                edits.append((lo + mention.start(), lo + mention.end(), fresh))
        results.append(edits)
    return results


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    result, every = [], []
    for family, edits in ((FAMILY_OR, _or_compound(source, part)), (FAMILY_NARROW, _narrow(source, part, header))):
        if edits:
            text = edit(source, edits)
            if text != source:
                result.append((family, text))
                every.extend(edits)
    webs = _split_webs(source, part)
    for edits in webs[:6]:
        text = edit(source, edits)
        if text != source:
            result.append((FAMILY_WEB, text))
    if webs:
        every.extend(edit_ for edits in webs[:6] for edit_ in edits)
    if len(result) > 1:
        text = edit(source, sorted(set(every)))
        if text != source:
            result.append((FAMILY_ALL, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 80}
