"""A place incremented through a temporary that is read again, written as `+=` with the later reads re-reading it.

m2c names the sum it saw in a register, stores it back and keeps using the name:

    sum = p->timer + 1;                              p->timer += 1;
    p->timer = sum;                          ->      p->phase += STEP;
    p->phase += STEP;                                p->frame = p->base + (p->timer >> 2);
    p->frame = p->base + (sum >> 2);

The game read the member again; the compiler reused the register itself. A named temporary is a value of the
function's own, allocated apart from the member's load and store, so the registers of the whole opening differ. On a
157-instruction N64 effect update (SN64 GCC, `-O2 -mips3`) this was the last step, 445 -> 0. That the temporary's own
pseudo is the reason is a hypothesis from that measurement; the judge decides each child.

Only where the re-read must give the same value: every read of the temporary is in the straight run of statements
after the store, with no call, label, brace or jump on the way, and every store on the way is to a local or to another
offset (or member) of the same base. The temporary has the place's own 32-bit type or the place is read through a
32-bit cast, so no truncation is lost. All qualifying temporaries at once first, then each alone."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, refs, view

FAMILY = 'field_increment_reread'
FAMILIES = (FAMILY,)
LIMIT = 6
_WORD = r'(?:s32|u32|int|long|unsigned|unsigned\s+int|signed\s+int|M2C_UNK)'
_CALL = re.compile(rf'\b(?!(?:M2C_FIELD|sizeof|__typeof__)\b){IDENT}\s*\(')
_BARRIER = re.compile(rf'[{{}}]|\b(?:if|else|for|while|do|switch|case|default|return|goto|break|continue)\b'
                      rf'|(?<![?\w]){IDENT}\s*:(?!:)')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _place(text):
    """(base, member, type) of a member or offset read through a base; None for anything else."""
    text = _squash(text)
    hit = re.fullmatch(rf'M2C_FIELD\(({IDENT}),(\w+)\*,({NUMBER})\)', text)
    if hit:
        return hit[1], str(int(hit[3].rstrip('uUlL'), 0)), hit[2]
    hit = re.fullmatch(rf'({IDENT})->({IDENT})', text)
    if hit:
        return hit[1], hit[2], None
    return None


def _apart(stored, kept):
    """Whether a store to `stored` cannot change `kept`: another offset or member of the same base."""
    one, other = _place(stored), _place(kept)
    return bool(one and other and one[0] == other[0] and one[1] != other[1] and (one[2] is None) == (other[2] is None))


def _site(part, source, decl):
    local = decl['name']
    mentions = refs(part, decl)
    if len(mentions) < 3 or not re.fullmatch(_WORD, ' '.join(decl['type'].split())):
        return None
    clean = part.clean
    first = mentions[0].start()
    if clean[part.opening:first].rstrip()[-1:] not in (';', '{', '}'):
        return None
    pair = re.compile(rf'{local}\s*=\s*(?P<place>[^;=]+?)\s*(?P<op>[-+])\s*(?P<step>{NUMBER})\s*;\s*'
                      rf'(?P<stored>[^;={{}}]+?)\s*=\s*{local}\s*;').match(clean, first)
    if not pair:
        return None
    place = pair['stored'].strip()
    if _squash(pair['place']) != _squash(place) or _CALL.search(place) or '++' in place or '--' in place:
        return None
    parts = _place(place)
    if parts is None and not re.fullmatch(IDENT, place):
        return None
    if parts and parts[2] and not re.fullmatch(_WORD, parts[2]):
        return None
    if parts and re.search(rf'\b{parts[0]}\s*=(?!=)', clean[pair.end():mentions[-1].end()]):
        return None
    reads = [hit for hit in mentions[1:] if hit.start() >= pair.end()]
    if len(reads) != len(mentions) - 2 or not reads:
        return None
    last_end = clean.find(';', reads[-1].start()) + 1
    if not last_end:
        return None
    run = clean[pair.end():last_end]
    if _BARRIER.search(re.sub(r'\?[^;:]*:', '?', run)) or _CALL.search(run) or '++' in run or '--' in run:
        return None
    local_names = {item['name'] for item in locals_for(part)}
    statements = run.split(';')[:-1]
    for index, statement in enumerate(statements):
        stored = re.match(r'\s*(?P<left>.+?)\s*(?:<<|>>|[-+*/%&|^])?=(?!=)', statement, re.S)
        if not stored:
            return None
        if re.search(r'(?<![=!<>])=(?!=)', statement[stored.end():]):
            return None
        left = stored['left'].strip()
        if left in local_names and left != local and left != place and (not parts or left != parts[0]):
            continue
        # (the last statement's own store comes after its reads)
        if index != len(statements) - 1 and not _apart(left, place):
            return None
    if parts is None and re.search(rf'\*|\bM2C_FIELD\b|->|\[|\b{place}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)',
                                   ';'.join(statements[:-1])):
        return None  # (a global: any store through a pointer may be to it)
    written = source[pair.start('stored'):pair.end('stored')].strip()
    edits = [(first, pair.end(), f"{written} {pair['op']}= {pair['step']};")]
    edits += [(hit.start(), hit.end(), written) for hit in reads]
    line = re.compile(rf'(?m)^[ \t]*{re.escape(decl["type"])}\s*{local}\s*;[ \t]*\n').search(source, part.opening)
    if line and line.start() <= decl.start() < line.end():
        edits.append((line.start(), line.end(), ''))
    return edits


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    sites = []
    for decl in locals_for(part):
        if decl['name'] not in [local for local, _ in sites] and (edits := _site(part, source, decl)):
            sites.append((decl['name'], edits))
    groups = [[edits for _, edits in sites]] if len(sites) > 1 else []
    groups += [[edits] for _, edits in sites]
    children = [edit(source, sorted({change for edits in group for change in edits})) for group in groups]
    return [(FAMILY, child) for child in dict.fromkeys(children) if child != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # registry.py
