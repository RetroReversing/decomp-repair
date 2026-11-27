"""A narrow member the function has just stored, read back instead of the local's mask or cast.

An N64 particle update (SN GCC 2.8.1, `-G0 -mips3 -O2`, 34 instructions) stored a halfword sum and then compared it
against a limit. m2c kept the sum in an `s16` local and wrote the compare with its mask:

    *(s16 *)((char *)arg0 + 0x6A) = sum;
    if (limit < (sum & 0xFFFF)) { ... }

which stores the halfword and then loads the limit one instruction too late (`sh` before `lw`; the target is `lw`,
`sh`, `andi`). The game compared the member itself, read as unsigned:

    if (limit < *(u16 *)((char *)arg0 + 0x6A)) { ... }

The compiler already has the value in a register, so the read costs no load and the `andi` stays. The search had
also put a `do { } while (0)` around the sum, which is why the read-back alone left the score where it was (60) and
opening the fence alone made it worse (640); both together were exact. So the children are offered as written, and
again with every one-shot fence opened.

A proposal takes a plain store of a local to an 8 or 16 bit member written with its type, `*(T *)(...) = t;` or
`M2C_FIELD(p, T *, off) = t;`, and the later statements of the same block (an `if` only for its condition) that read
`t` masked or cast to the member's width (`(t & 0xFFFF)`, `(u16) t`, `(s16) t`, `(t & 0xFF)`, `(u8) t`), or `t`
itself when its declared type is the member's. Each such read is written as the member with the matching signedness,
which has the same value. Between the store and a read nothing may call, and nothing may be written but another
local or a member of the same base at offsets that don't overlap the stored one (`M2C_FIELD` and `*(T *)((u8 *)p + K)`
forms).

m2c also writes the store itself through a cast of the member's width (an N64 sprite pulse routine, SN GCC 2.8.1, 50
instructions):

    M2C_FIELD(arg0, s8 *, 0x77) = (s8) frame;
    M2C_FIELD(arg0, s32 *, 0x34) = timer;
    next = (frame & 0xFF) % 5U;

where the game divided the member it had just stored (`next = *(u8 *)member % 5U;`). The target's `andi` of the stored
register comes from that read: with the mask on the local the remainder was 635, with the read-back exact. So a stored
value spelled `(s8) t` or `(u8) t` (the member's width) stands for `t` too, and the other member's store between does
not end the walk.
This module reads text only and never compiles or judges."""
import re

from .fence_regroup import _fences
from .field_copy_reread import _field, _may_touch
from .hand_found_support import IDENT, NUMBER, blocks, calls_in, local_type, simple, stmts, store_target, writes
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'stored_member_readback'
UNFENCED = 'stored_member_readback_unfenced'
FAMILIES = (FAMILY, UNFENCED)
MAX_CHILDREN = 8
WINDOW = 12  # statements after the store that may hold a read

_WIDTHS = {'s8': (1, True), 'u8': (1, False), 's16': (2, True), 'u16': (2, False)}
_SPELLED = {(size, signed): kind for kind, (size, signed) in _WIDTHS.items()}
# `*(T *)p`, `(*(T *)p)` and `*((T *) (p))`: the printed form wraps the whole cast expression after the `*`.
_CAST_STORE = re.compile(r'\(?\s*\*\s*(?P<wrap>\(\s*)?\(\s*(?:volatile\s+)?(?P<kind>[su](?:8|16))\s*\*\s*\)')
_FIELD_STORE = re.compile(rf'M2C_FIELD\s*\(\s*{IDENT}\s*,\s*(?P<kind>[su](?:8|16))\s*\*\s*,\s*{NUMBER}\s*\)')


def _member(text):
    """(kind, start of the kind, end of it) of a store target that spells its narrow type; None for anything else."""
    found = _FIELD_STORE.fullmatch(text)
    if not found:
        found = _CAST_STORE.match(text)
        if not found or re.search(r'\[|->', text[found.end():]):
            return None
        # The cast must cover the whole lvalue: what follows is one parenthesised address or one name.
        rest = text[found.end():].strip()
        for _ in range(text.startswith('(') + bool(found['wrap'])):
            if not rest.endswith(')'):
                return None
            rest = rest[:-1].strip()
        if not re.fullmatch(IDENT, rest):
            if not rest.startswith('(') or close(rest, 0, '(', ')') != len(rest):
                return None
    return found['kind'], found.start('kind'), found.end('kind')


def _read(lvalue, member, size, signed):
    kind, start, end = member
    wanted = kind if _WIDTHS[kind] == (size, signed) else _SPELLED[(size, signed)]
    text = lvalue[:start] + wanted + lvalue[end:]
    return text if text.startswith('(') and close(text, 0, '(', ')') == len(text) else f'({text})'


def _stored_local(value, size):
    """The local a store's value names: `t` itself, or `t` cast to a type of the member's width; None otherwise."""
    if re.fullmatch(IDENT, value):
        return value
    found = re.fullmatch(rf'\(\s*(?P<kind>[su](?:8|16))\s*\)\s*(?P<local>{IDENT})', value)
    return found['local'] if found and _WIDTHS[found['kind']][0] == size else None


def _other_member(target, lvalue):
    """True when `target` is a member of the stored member's base that cannot overlap it."""
    stored, other = _field(lvalue), _field(target)
    return bool(stored and other and not _may_touch(other, stored))


def _reads(clean, lo, hi, local, same_type, lvalue, member):
    """[(start, end, replacement)] of the reads of `local` in clean[lo:hi] that the member can stand for."""
    n = re.escape(local)
    size, signed = _WIDTHS[member[0]]
    mask = '0[xX]0*[fF]{4}|65535' if size == 2 else '0[xX]0*[fF]{2}|255'
    casts = {'u16': (2, False), 'unsigned short': (2, False), 's16': (2, True), 'short': (2, True),
             'u8': (1, False), 'unsigned char': (1, False), 's8': (1, True), 'signed char': (1, True)}
    text = clean[lo:hi]
    found = []
    for hit in re.finditer(rf'\(\s*(?P<read>{n}\s*&\s*(?:{mask}))\s*\)', text):
        found.append((lo + hit.start('read'), lo + hit.end('read'), _read(lvalue, member, size, False)))
    for hit in re.finditer(rf'\(\s*(?P<kind>{"|".join(casts)})\s*\)\s*{n}\b(?!\s*(?:\[|\.|->|\())', text):
        if casts[hit['kind']][0] == size:
            found.append((lo + hit.start(), lo + hit.end(), _read(lvalue, member, *casts[hit['kind']])))
    if same_type:
        for hit in re.finditer(rf'(?<![\w.>&]){n}\b(?!\s*(?:\[|\.|->|\(|\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=)))', text):
            at = lo + hit.start()
            if not any(a <= at < b for a, b, _ in found):
                found.append((at, at + len(local), _read(lvalue, member, size, signed)))
    return sorted(found)


def _readbacks(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        for k, (start, end) in enumerate(spans):
            if not simple(clean[start:end]):
                continue
            hit = store_target(clean[start:end])
            if not hit or calls_in(hit[0]):
                continue
            lvalue = hit[0]
            member = _member(lvalue)
            local = member and _stored_local(hit[1], _WIDTHS[member[0]][0])
            kind = local and local_type(part, local)
            if not kind:
                continue
            names = set(re.findall(IDENT, lvalue))
            found = []
            for a, b in spans[k + 1:k + 1 + WINDOW]:
                text = clean[a:b]
                head = re.match(r'\s*if\s*\(', text)
                if head:
                    stop = close(clean, a + head.end() - 1, '(', ')')
                    if stop and not calls_in(clean[a + head.end():stop - 1]):
                        reads = _reads(clean, a + head.end() - 1, stop, local, kind == member[0], lvalue, member)
                        if reads:
                            found.append(reads)
                    break
                if not simple(text) or calls_in(text) or re.search(r'\+\+|--', text):
                    break
                assigned = store_target(text)
                target = assigned[0] if assigned else None
                if target is None:
                    compound = re.match(rf'\s*({IDENT})\s*(?:[-+*/%&|^]|<<|>>)=', text)
                    target = compound[1] if compound else None
                if target is None:
                    break
                elsewhere = assigned is not None and _other_member(target, lvalue)
                if not elsewhere and (not re.fullmatch(IDENT, target) or not local_type(part, target)):
                    break
                value_at = a + text.index('=') + 1
                reads = _reads(clean, value_at, b, local, kind == member[0], lvalue, member)
                if reads:
                    found.append(reads)
                if target in names or writes(text, local):
                    break
            if not found:
                continue
            # The text as written (comments are blanked in `clean`).
            spelled = source[start:end]
            written = spelled[spelled.index(spelled.strip()[0]):].split('=', 1)[0].strip()
            if written != lvalue.strip():
                continue
            if len(found) > 1:
                out.append(edit(source, [read for reads in found for read in reads]))
            out.extend(edit(source, reads) for reads in found)
    return out


def _unfence(source, name):
    """Every one-shot `do { S } while (0);` written as the block `{ S }`; None when there is none."""
    text = source
    for _ in range(64):
        part = view(text, name)
        fences = _fences(part) if part else []
        if not fences:
            break
        start, brace, end, stop = fences[0]
        text = text[:start] + text[brace:end] + text[stop:]
    return text if text != source else None


def variants(source, name):
    """Proposals: a narrow member just stored, read back where the local was masked or cast; as written, and with the
    one-shot fences opened."""
    out = [(FAMILY, child) for child in _readbacks(source, name)[:MAX_CHILDREN]]
    opened = _unfence(source, name)
    if opened:
        out += [(UNFENCED, child) for child in _readbacks(opened, name)[:MAX_CHILDREN]]
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
