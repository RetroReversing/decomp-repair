"""Address-taking fences and dead `if (0) goto` ladders a search left in a function, written out so the frame shrinks.

    s32 temp_v0;
    (void) (&temp_v0);                      <- the local lives in the frame, never in a register
    loop_goto_1:
    { temp_v0 = (arg0 & 0xFF) * 0xC; }
    if (0) { goto loop_goto_1; }            <- never runs, but keeps a loop-shaped label alive

Both are search scaffolding (`address_taken_local` adds the first to force a frame slot, the loop-goto forms add the
second): each is neutral to the code it surrounds and costs the function nothing in the target, but while it stays the
compiler keeps what it implies. `(void) (&x);` takes the address of `x`, so `x` is a memory slot (GCC 2.7 does not
allocate a register for an addressable local): the frame grows by its slot, here 8 bytes, and every access to the local
is a load or store through `$sp` where the target keeps it in a register (104 -> 0 on a 6-instruction wrapper with a
single `* 0xC` index, once both were removed). The `if (0)` jump to a label is deleted by the front end, but the label
before the block still ends the basic block and splits the value's live range.

Children, each only where the program's meaning is kept:
  * `frame_fence_strip_address`: every statement `(void) (&x);` / `(void)&x;` (a bare address-of cast to void) goes;
  * `frame_fence_strip_goto`: every `if (0) goto L;` / `if (0) { goto L; }` (also `if (0 != 0)`, `if (FALSE)`) goes,
    and a label `L:` that no remaining `goto L` reaches goes with it, the plain block it labelled opened into its
    statements when it declares nothing;
  * `frame_fence_strip`: both together.
Nothing is offered for a function with neither, and a function with an `asm` block or a `goto` that can run (a
`goto L;` outside a dead `if (0)`) keeps its labels. A candidate for the exact judge; the frame size is read from the
judge's rows, not decided here."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'frame_fence_strip'
FAMILY_ADDRESS = 'frame_fence_strip_address'
FAMILY_GOTO = 'frame_fence_strip_goto'
FAMILIES = (FAMILY, FAMILY_ADDRESS, FAMILY_GOTO)
FENCE = re.compile(rf'(?m)^[ \t]*\(\s*void\s*\)\s*\(?\s*&\s*{IDENT}\s*\)?\s*;[ \t]*\n?')
DEAD_TEST = r'\(\s*(?:0|0\s*!=\s*0|FALSE|false)\s*\)'
DEAD_JUMP = re.compile(rf'(?m)^[ \t]*if\s*{DEAD_TEST}\s*(?:\{{\s*goto\s+(?P<a>{IDENT})\s*;\s*\}}|goto\s+(?P<b>{IDENT})\s*;)[ \t]*\n?')
DECLARES = re.compile(rf'(?m)^\s*(?:register\s+|const\s+|volatile\s+)*(?:unsigned\s+|signed\s+)?{IDENT}[\s*]+{IDENT}\s*(?:=[^;]*|\[[^\]]*\])?;')


def _label_edit(clean, label, opening):
    """The edits that remove `label:` (and unwrap the plain block right after it when it declares nothing)."""
    hit = re.compile(rf'(?m)^([ \t]*){re.escape(label)}[ \t]*:[ \t]*\n?').search(clean, opening)
    if not hit:
        return []
    edits = [(hit.start(), hit.end(), '')]
    brace = re.compile(r'[ \t]*\{').match(clean, hit.end())
    if brace:
        start = brace.end() - 1
        stop = close(clean, start, '{', '}')
        inner = clean[start + 1:stop - 1] if stop else None
        if inner is not None and not DECLARES.search(inner) and not re.search(rf'\b{re.escape(label)}\b|\bcase\b|\bdefault\b', inner) \
                and not re.search(r'\b(?:break|continue)\b', inner):
            after = re.compile(r'[ \t]*\n?').match(clean, stop)
            edits.append((brace.start(), start + 1, ''))
            edits.append((stop - 1, after.end() if after else stop, ''))
    return edits


def strip_address(source, name):
    part = view(source, name)
    if not part:
        return None
    edits = [(part.opening + m.start() + 1, part.opening + m.end() + 1, '') for m in FENCE.finditer(part.body)]
    return edit(source, edits) if edits else None


def strip_goto(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|switch)\b', part.body):
        return None
    clean, body_at = part.clean, part.opening + 1
    edits, dead = [], []
    for m in DEAD_JUMP.finditer(part.body):
        edits.append((body_at + m.start(), body_at + m.end(), ''))
        dead.append((m['a'] or m['b'], body_at + m.start(), body_at + m.end()))
    if not edits:
        return None
    gone = [(a, b) for _, a, b in dead]
    for label, _, _ in dead:
        reaching = [m for m in re.finditer(rf'\bgoto\s+{re.escape(label)}\s*;', part.body)
                    if not any(a <= body_at + m.start() < b for a, b in gone)]
        if reaching:
            continue
        label_edits = _label_edit(clean[:part.end], label, part.opening)
        if label_edits and not any(a < e[1] and e[0] < b for e in label_edits for a, b in gone):
            edits += label_edits
    return edit(source, sorted(set(edits))) if edits else None


def variants(source, name):
    address = strip_address(source, name)
    jumps = strip_goto(source, name)
    out = []
    if address and jumps:
        both = strip_goto(address, name)
        if both:
            out.append((FAMILY, both))
    if address:
        out.append((FAMILY_ADDRESS, address))
    if jumps:
        out.append((FAMILY_GOTO, jumps))
    return [(f, t) for f, t in out if t != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
