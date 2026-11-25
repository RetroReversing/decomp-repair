"""A local array declared one element larger and indexed from 1, so its used elements sit one element higher.

m2c names a stack local by the offset the target gives it, and a draft that declares `Vec3 pts[4]` and reads
`pts[0]` .. `pts[3]` puts the base at the bottom of the locals. The game's frame had the used elements one element
higher (`0x10($sp)` more for a 16-byte record): its array was one longer and its code started at `pts[1]` (the first
element never used; the hand matches of two SN GCC 2.8.1 vector routines were exact only with `Vec3 pts[5]` and
`pts[1]` .. `pts[4]`, the frame size unchanged because the array's tail was padding). The stack rows of the diff are
all off by one element and nothing else says why.

For a local array `T name[N];` whose every use is `name[index]` (no bare `name`, no `&name` of the whole array, no `sizeof(name)`; `&name[i]` is an element use),
the child declares `T name[N + 1];` and adds 1 to every index (a literal as the next literal, any other index as
`(index) + 1`). One child per array, at most `LIMIT`; a function with `volatile`, `asm` or a preprocessor line is left
alone. When the target's assembly is given the child is offered only if the target addresses its frame (`$sp`)
at all. The judge decides."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'array_index_from_one'
FAMILIES = (FAMILY,)
LIMIT = 4
_DECL = re.compile(rf'(?m)^([ \t]*)((?:(?:unsigned|signed|struct|const)\s+)*{IDENT})\s+({IDENT})\s*\[\s*(\d+)\s*\]\s*;')
_NOT_TYPE = {'return', 'goto', 'else', 'case', 'extern', 'typedef', 'static'}


def _python_index_end(clean, at):
    depth = 1
    while at < len(clean) and depth:
        depth += {'[': 1, ']': -1}.get(clean[at], 0)
        at += 1
    return at - 1 if not depth else -1


_index_end = _python_index_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _index_end(clean, at):
        found = _scan.unmatched_close(clean, at, '[', ']', -1)
        return _python_index_end(clean, at) if found is NotImplemented else found


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body, re.M):
        return []
    if asm and not re.search(r'\(\s*\$sp\s*\)|\$sp\s*,', asm):
        return []
    out = []
    for decl in _DECL.finditer(part.clean, part.opening + 1, part.end):
        kind, array, count = decl[2], decl[3], int(decl[4])
        if kind.split()[-1] in _NOT_TYPE or count < 1 or count > 64:
            continue
        uses = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(array)}\b', part.clean[decl.end():part.end])]
        edits, ok = [(decl.start(4), decl.end(4), str(count + 1))], bool(uses)
        for use in uses:
            start = decl.end() + use.start()
            after = part.clean[decl.end() + use.end():].lstrip()
            before = part.clean[:start].rstrip()
            if not after.startswith('[') or before.endswith('sizeof(') or before.endswith('sizeof'):
                ok = False
                break
            open_at = decl.end() + use.end() + (len(part.clean[decl.end() + use.end():]) - len(after))
            close = _index_end(part.clean, open_at + 1)
            if close < 0:
                ok = False
                break
            index = part.clean[open_at + 1:close].strip()
            if re.fullmatch(r'\d+', index):
                edits.append((open_at + 1, close, str(int(index) + 1)))
            elif re.fullmatch(r'0[xX][0-9a-fA-F]+', index):
                edits.append((open_at + 1, close, str(int(index, 16) + 1)))
            else:
                edits.append((open_at + 1, close, f'({index}) + 1' if not re.fullmatch(r'\w+', index) else f'{index} + 1'))
        if ok:
            out.append((FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
