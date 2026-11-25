"""A pointer loaded again through the same field, read through the local that already holds the first load.

m2c gives the first use of a loaded pointer a local (`temp_s0 = *(void **)(obj + 0x6C);`) and spells the later loads
of the same field out in the statements that use them (`*(s32 *)((char *)(*(void **)((char *)other + 0x6C)) + 0x24) =
v;`). Every use of a source variable is one pseudo for GCC 2.7, which ranks pseudos for the saved registers by
`floor_log2(uses) * uses / live length` and which hands the longest-lived, most-used one `$s0`. The target loaded the
pointer into the same register each time (`lw $s0,0x6c($v0)` for all three), so its uses added up and the pointer
took `$s0` where the draft's one use per pseudo left it in `$v0`/`$v1` temporaries. (A 180-instruction N64 function,
`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`: 1110 -> 1090 alone, 620 -> 600 beside the loop repairs.)

For each local `P` assigned `P = *((void **) (((char *) B) + OFF));`, each later single-line statement that contains
`(*((void **) (((char *) E) + OFF)))` with the same `OFF` is offered with that load assigned to `P` on the line
above and the statement reading `P`; every such statement alone, and all of them together. `P` must have no mention
the new assignment could change: every other mention of it follows an assignment of `P` in the same block.
A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, edit, view
from .loop_address_hoist_repairs import _loops

FAMILIES = ('loaded_pointer_reuse',)
LIMIT = 8
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LOAD = rf'\*\s*\(\(\s*void\s*\*\*\s*\)\s*\(\s*\(\(\s*char\s*\*\s*\)\s*(?P<base>[^()]+?)\s*\)\s*\+\s*(?P<off>{NUM})\s*\)\s*\)'
ASSIGN = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<p>{IDENT})\s*=\s*{LOAD}\s*;[ \t]*$')
EMBEDDED = re.compile(rf'\(\s*{LOAD}\s*\)')


def _python_block(clean, at):
    depth = 0
    for pos in range(at-1, -1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos
            depth -= 1
    return -1


_block = _python_block
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block(clean, at):
        found = _scan.enclosing_open(clean, at, 0, -1)
        return _python_block(clean, at) if found is NotImplemented else found


def _safe(clean, p, sites, opening, end):
    """Every mention of `p` outside the new assignments follows an assignment of `p` in its own block, and inside a
    loop that holds a new assignment, one made in that loop (an earlier iteration's value is never read)."""
    loops = [span for span in _loops(clean, opening, end) if any(span[0] <= site[0] < span[1] for site in sites)]
    for m in re.finditer(rf'(?<![\w.>]){re.escape(p)}\b', clean[opening:end]):
        at = opening+m.start()
        if re.match(r'\s*=(?!=)', clean[opening+m.end():end]):
            continue
        line = clean.rfind('\n', 0, at)+1
        if re.fullmatch(rf'[ \t]*(?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*\**[ \t]*{re.escape(p)}[ \t]*;[ \t]*', clean[line:clean.find('\n', at)]):
            continue
        for span in loops:
            if span[0] <= at < span[1] and not re.search(rf'(?<![\w.>]){re.escape(p)}\s*=(?!=)', clean[span[0]:at]):
                return False
        head = _block(clean, at)
        while head >= opening:
            if re.search(rf'(?<![\w.>]){re.escape(p)}\s*=(?!=)', clean[head:at]):
                break
            head = _block(clean, head)
        else:
            return False
    return True


def _build(source, clean, assign, chosen):
    """The source with each chosen statement reading `p`, the load assigned to it on the line above."""
    p = assign['p']
    edits = []
    for line_start, text_start, hit in chosen:
        indent = clean[line_start:text_start]
        load = source[assign.start('p') + len(p):assign.end()].split('=', 1)[1].strip()
        load = re.sub(r'(?<=\(\(char \*\) )[^()]+?(?=\) \+)', hit['base'].strip(), load, count=1)
        edits.append((line_start, line_start, f'{indent}{p} = {load}\n'))
        edits.append((text_start+hit.start(), text_start+hit.end(), p))
    return edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for assign in ASSIGN.finditer(clean, part.opening, part.end):
        p, off = assign['p'], int(assign['off'], 0)
        if re.search(rf'&\s*{re.escape(p)}\b', clean[part.opening:part.end]):
            continue
        sites = []
        for line in re.finditer(r'(?m)^([ \t]*)([^\n{};]*;)[ \t]*$', clean[assign.end():part.end]):
            text = line[2]
            if re.match(r'\s*(?:if|else|while|for|do|switch|return|goto)\b', text):
                continue
            hits = [m for m in EMBEDDED.finditer(text) if int(m['off'], 0) == off]
            if len(hits) != 1 or hits[0]['base'].strip() == p or p in re.findall(IDENT, hits[0]['base']):
                continue
            if re.search(rf'\b{re.escape(p)}\b', text):
                continue
            sites.append((assign.end()+line.start(), assign.end()+line.start(2), hits[0]))
        if not sites or not _safe(clean, p, sites, part.opening, part.end):
            continue

        out += [_build(source, clean, assign, [one]) for one in sites]
        if len(sites) > 1:
            out.append(_build(source, clean, assign, sites))
    result = []
    for text in out:
        if text != source and text not in result:
            result.append(text)
    return [(FAMILIES[0], c) for c in result[:LIMIT]]
