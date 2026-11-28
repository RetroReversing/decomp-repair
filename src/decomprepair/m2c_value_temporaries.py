"""m2c's block temporaries holding memory reads and index arithmetic, written back where they are used.

m2c names what the compiler's register reuse kept: the index, the index times two, a table element's address, the
element itself, and after cross-jumping the same value under a new name in each path. Each temporary assigned again in
another block, each held in a pointer or a narrow type, keeps `single_use_inline` (read once), `reread_temporary_inline`
(a call between) and `shared_value_inline` (set once, `s32`) away, and writing out only one leaves the others tying the
registers.

m2c_value_temporaries
    Every local whose reads all follow an assignment in the same block, from an expression with no call or side effect,
    with no call and no store to anything the expression names in between, is written out at each read and its
    declaration and assignments dropped, all such locals together.
m2c_value_temporaries_readback
    The same, where a read after `object->member = temporary;` reads the member back.

Seen on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 label update: 3650 with the temporaries and 0 without them (one
function, a controlled result). Stores through other pointers are assumed not to alias; the judge decides.
"""
import re

from .c_scan import enclosing_block
from .csource import _blank, find
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'm2c_value_temporaries'
READBACK = 'm2c_value_temporaries_readback'
FAMILIES = (FAMILY, READBACK)

_ID = r'[A-Za-z_]\w*'
_NARROW = ('u8', 's8', 'u16', 's16')
_NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD'}
_TYPE_WORDS = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'char', 'void', 'struct', 'volatile', 'const'}


def _calls(text):
    return any(m[1] not in _NOT_CALLS for m in re.finditer(rf'(?<![\w.>])({_ID})\s*\(', text))


def _stores(text):
    """The names `text` stores to, or None when it stores through a pointer it computes."""
    names = set()
    for m in re.finditer(r'(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--', text):
        left = text[:m.start()].rstrip()
        statement = left[max(left.rfind(';'), left.rfind('{'), left.rfind('}')) + 1:].strip()
        if statement.startswith('*') or re.match(r'\(\s*\*', statement) and '->' not in statement:
            return None
        left, count = left.rstrip(') '), 1
        while count and left.endswith(']'):  # the subscripts of an element
            left, count = re.subn(r'\[[^\[\]]*\]\)*$', '', left)
            left = left.rstrip(') ')
        name = re.search(rf'({_ID})$', left)
        if name:
            names.add(name[1])
    return names


def _block_end(clean, position, end):
    """Where the innermost block around `position` closes."""
    opening = enclosing_block(clean, position, 0)
    closing = close(clean, opening, '{', '}') if opening >= 0 else None
    return closing - 1 if closing else end


def _statement_start(clean, position):
    return max(clean.rfind(mark, 0, position) for mark in ';{}') + 1


def _kept(clean, start, read, words):
    """Whether a value read at `start` is still the same at `read`."""
    between = clean[start:max(start, _statement_start(clean, read))]
    stored = _stores(between)
    return not _calls(between) and stored is not None and not stored & words


def _one(source, name, readback):
    """`source` with the first qualifying local written out, or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    declaration = re.compile(rf'(?m)^[ \t]*(?P<type>{_ID})(?:[ \t]+|[ \t]*\*+[ \t]*)(?P<name>{_ID})[ \t]*;[ \t]*\n')
    for declared in declaration.finditer(clean, opening, end):
        local, kind = declared['name'], declared['type']
        if kind in ('return', 'goto', 'volatile'):
            continue
        sets = [s for s in re.finditer(rf'(?m)^[ \t]*{local}[ \t]*=(?!=)\s*(?P<value>[^;{{}}]+);[ \t]*\n', clean[:end])
                if s.start() > opening]
        if not sets:
            continue
        reads = [m for m in re.finditer(rf'(?<![\w.>]){local}\b', clean[:end])
                 if m.start() > opening and not declared.start() <= m.start() < declared.end()]
        reads = [m for m in reads if not any(s.start() <= m.start() < s.start('value') for s in sets)]
        if re.search(rf'(?:\+\+|--|(?<![&\w)\]])&)\s*{local}\b|(?<![\w.>]){local}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)',
                     clean[opening:end]):
            continue
        edits, covered = [(declared.start(), declared.end(), '')], set()
        for number, assigned in enumerate(sets):
            value = assigned['value'].strip()
            if _calls(value) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\bvolatile\b', value) \
                    or re.search(rf'(?<![\w.>]){local}\b', value):
                break
            if kind in _NARROW:
                member = re.search(r'->\s*(\w+)\)*$', value)
                if not member or not re.search(rf'\b{kind}\s+{member[1]}\s*;', clean):
                    break
            words = set(re.findall(rf'(?<![\w])({_ID})', value)) - _TYPE_WORDS
            stop = _block_end(clean, assigned.end(), end)
            if number + 1 < len(sets):
                stop = min(stop, sets[number + 1].start())
            written = source[assigned.start('value'):assigned.end('value')].strip()
            if not re.fullmatch(rf'\w+|&?{_ID}\[[^\[\]]*\]', written) \
                    and not (written.startswith('(') and close(written, 0) == len(written)):
                written = f'({written})'
            stores = []
            if readback:
                stores = list(re.finditer(rf'(?m)^[ \t]*(?P<to>[^;{{}}=\n]*->\s*(?P<member>\w+)\)?)[ \t]*=[ \t]*'
                                          rf'(?:\(\s*s32\s*\)\s*)?{local}\s*;', clean[:stop]))
                stores = [s for s in stores if s.start() >= assigned.end()]
            edits.append((assigned.start(), assigned.end(), ''))
            for read in reads:
                if not assigned.end() <= read.start() < stop:
                    continue
                new = written
                for store in stores:
                    if (store.end() <= read.start() <= _block_end(clean, store.end(), end)
                            and _kept(clean, store.end(), read.start(), {store['member']})):
                        new = source[store.start('to'):store.end('to')].strip()
                        break
                if new == written and not _kept(clean, assigned.end(), read.start(), words):
                    break
                edits.append((read.start(), read.end(), new))
                covered.add(read.start())
            else:
                continue
            break
        else:
            if covered == {read.start() for read in reads}:
                text = edit(source, edits)
                return re.sub(rf'\*\s*\(?&({_ID}\[[^\[\]]*\])\)?', r'\1', text)
    return None


def _all(source, name, readback):
    text, changed = source, 0
    for _ in range(40):
        step = _one(text, name, readback)
        if step is None:
            break
        text, changed = step, changed + 1
    return text if changed > 1 else None


def variants(source, name):
    result = []
    for family, readback in ((READBACK, True), (FAMILY, False)):
        text = _all(source, name, readback)
        if text and text not in [t for _, t in result]:
            result.append((family, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
