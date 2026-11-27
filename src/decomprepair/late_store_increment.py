"""An increment m2c held in a local and stored later, written as `+=` where it was computed, with a narrow readback.

An N64 effect update (SN GCC 2.8.1, `-G0 -mips3 -O2 -mgas -mfp64`, 31 instructions) bumped a record's counter, added to
a phase word, stored colour bytes and a halfword height, and tested the height. m2c named both sums and put the
counter's store where the target has it, after the phase's:

    timer = M2C_FIELD(p, s32 *, 0x34) + 1;                M2C_FIELD(p, s32 *, 0x34) += 1;
    phase = M2C_FIELD(p, s32 *, 0x3C) + STEP;             M2C_FIELD(p, s32 *, 0x3C) += STEP;
    M2C_FIELD(p, s32 *, 0x3C) = phase;            ->      ...
    ...
    M2C_FIELD(p, s32 *, 0x34) = timer;
    height = base + (timer >> 2);                         height = base + (M2C_FIELD(p, s32 *, 0x34) >> 2);
    M2C_FIELD(p, s16 *, 0x6A) = height;                   M2C_FIELD(p, s16 *, 0x6A) = height;
    if (limit < (height & 0xFFFF))                        if (limit < M2C_FIELD(p, u16 *, 0x6A))

The game updated the members in place and tested the stored halfword; the scheduler moved the counter's store down by
itself. The draft was 990, the `+=` half alone 1260, the readback alone 1610, and both together exact.
`field_increment_reread` needs the store right after the sum, so it rewrote only the phase.

A proposal takes `t = F + K;` (or `- K`; `F` a 32-bit field of a record, `t` a 32-bit local) and the later `F = t;` of
the same block. Between them only plain statements run: they call nothing, write a local or another field of the same
record that cannot overlap `F`, and touch no memory but such fields. After the store, up to the last read of `t`, the
same holds for what is written, and an `if` may read it in its condition. So `F` holds `t` at every read. All such
locals are rewritten at once (then each alone), each child also with the narrow members it stores read back
(`stored_member_readback`). This module reads text only and never compiles or judges."""
import re

from .hand_found_support import IDENT, NUMBER, blocks, calls_in, local_type, simple, stmts, store_target
from .integer_repair_support import edit, locals_for, refs, view
from .pattern_repairs import close
from .stored_compare_readback import _CAST, _MACRO, _apart, _field
from .stored_member_readback import _readbacks

FAMILY = 'late_store_increment_reread'
FAMILY_READBACK = 'late_store_increment_readback'
FAMILIES = (FAMILY, FAMILY_READBACK)
MAX_CHILDREN = 8
WINDOW = 20  # statements from the sum to its last read

_WORDS = ('s32', 'u32', 'int', 'long', 'unsigned', 'unsigned int', 'signed int', 'M2C_UNK')
_TYPES = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'f32', 'char', 'short', 'int', 'long', 'signed', 'unsigned', 'float',
          'void'}
_COMPOUND = re.compile(r'\s*(?P<left>[^;=]+?)\s*(?:<<|>>|[-+*/%&|^])=(?!=)')
_ARROW = re.compile(rf'(?<![\w.>]){IDENT}\s*->\s*{IDENT}')


def _squash(text):
    return re.sub(r'\s+', '', text)


def _only_apart(part, text, stored):
    """True when every memory access spelled in `text` is a field that cannot overlap `stored`."""
    for pattern in (_CAST, _MACRO, _ARROW):
        for hit in reversed(list(pattern.finditer(text))):
            if not _apart(stored, _field(part.clean, part, hit[0])):
                return False
            text = text[:hit.start()] + ' 0 ' + text[hit.end():]
    if re.search(r'->|\[|\.\s*[A-Za-z_]|M2C_FIELD|&(?!&)\s*[A-Za-z_]\w*\s*[,);]', text):
        return False
    if re.search(r'(?:^|[=(,+\-*/%&|^<>!~?:])\s*\*', text.strip()):
        return False  # (a dereference)
    return all(name in _TYPES or local_type(part, name) for name in re.findall(r'(?<![\w.])[A-Za-z_]\w*', text))


def _plain(part, text, stored, local):
    """True for a plain statement that writes a local or a field apart from `stored`, and leaves `local` and the base
    of the record alone."""
    if not simple(text) or calls_in(text) or re.search(r'\+\+|--', text):
        return False
    compound = _COMPOUND.match(text)
    hit = compound or store_target(text)
    if not hit:
        return False
    target = (compound['left'] if compound else hit[0]).strip()
    if re.fullmatch(IDENT, target):
        return target not in (local, stored[0]) and bool(local_type(part, target))
    return _apart(stored, _field(part.clean, part, target))


def _site(part, source, decl):
    """The edits for one local, and whether its store is away from the sum; None when it is not that shape."""
    local = decl['name']
    clean = part.clean
    if ' '.join(decl['type'].split()) not in _WORDS:
        return None
    mentions = refs(part, decl)
    if len(mentions) < 3:
        return None
    first = mentions[0].start()
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        k = next((i for i, (a, b) in enumerate(spans) if a <= first < b and not clean[a:first].strip()), None)
        if k is not None:
            break
    else:
        return None
    start, end = spans[k]
    total = re.fullmatch(rf'\s*{local}\s*=\s*(?P<place>[^;=]+?)\s*(?P<op>[-+])\s*(?P<step>{NUMBER})\s*;\s*',
                         clean[start:end])
    if not total or calls_in(total['place']):
        return None
    place = total['place'].strip()
    stored = _field(clean, part, place)
    if not stored or stored[1] not in _WORDS or stored[0] == local:
        return None
    last = mentions[-1].start()
    store = None
    for j in range(k + 1, min(len(spans), k + 1 + WINDOW)):
        a, b = spans[j]
        text = clean[a:b]
        hit = simple(text) and store_target(text)
        if store is None:
            if hit and hit[1] == local and _squash(hit[0]) == _squash(place):
                store = j
                if b > last:
                    return None  # (no later read)
                continue
            if not _plain(part, text, stored, local) or not _only_apart(part, text.replace(local, '0'), stored):
                return None
            continue
        if a <= last < b:
            head = re.match(r'\s*if\s*\(', text)
            if head:
                stop = close(clean, a + head.end() - 1, '(', ')')
                if not stop or last >= stop or calls_in(clean[a + head.end():stop - 1]) or re.search(
                        r'\+\+|--', clean[a:stop]):
                    return None
            elif not _plain(part, text, stored, local):
                return None
            break
        if not _plain(part, text, stored, local):
            return None
    else:
        return None
    if store is None or not clean[spans[store][0]:spans[store][1]].strip():
        return None
    a, b = spans[store]
    a += len(clean[a:b]) - len(clean[a:b].lstrip())
    written = source[total.start('place') + start:total.end('place') + start].strip()
    edits = [(first, start + len(clean[start:end].rstrip()), f"{written} {total['op']}= {total['step']};")]
    line_start = source.rfind('\n', 0, a) + 1
    line_end = source.find('\n', b - 1)
    if not source[line_start:a].strip() and line_end >= 0 and not source[a:line_end].partition(';')[2].strip():
        edits.append((line_start, line_end + 1, ''))
    else:
        edits.append((a, a + clean[a:b].index(';') + 1, ''))
    read = f'({written})' if written.startswith('*') else written
    for hit in mentions[1:]:
        if not a <= hit.start() < b:
            edits.append((hit.start(), hit.end(), read))
    declaration = re.compile(rf'(?m)^[ \t]*{re.escape(decl["type"])}\s*{local}\s*;[ \t]*\n').search(source, part.opening)
    if declaration and declaration.start() <= decl.start() < declaration.end():
        edits.append((declaration.start(), declaration.end(), ''))
    return edits, store > k + 1


def variants(source, name):
    """Proposals: the sums stored later written as `+=` in place; each also with the narrow stored members read back."""
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|union|asm|__asm__)\b', part.clean):
        return []
    sites = {}
    for decl in locals_for(part):
        if decl['name'] not in sites and (found := _site(part, source, decl)):
            sites[decl['name']] = found
    if not sites:
        return []
    # All of them first, one rewrite after another: each is read again, as the others' places change the text.
    child, names, apart = source, [], False
    for local in sites:
        part = view(child, name)
        decl = next((d for d in locals_for(part) if d['name'] == local), None)
        found = decl and _site(part, child, decl)
        if found:
            child = edit(child, found[0])
            names.append(local)
            apart = apart or found[1]
    children = [(child, apart)] if names else []
    if len(sites) > 1:
        children += [(edit(source, edits), away) for edits, away in sites.values()]
    out = []
    for text, away in children:
        # A read that loses its mask or cast first: that is the halfword compare the readback is for.
        again = sorted(_readbacks(text, name), key=lambda c: c.count('&') + c.count('(u'))
        out += [(FAMILY_READBACK, other) for other in again[:2]]
        if away:  # (a store right after its sum is `field_increment_reread`'s own child)
            out.append((FAMILY, text))
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
