"""A run of m2c's stack locals, one array whose first element's address escapes, declared as that array again.

m2c names a stack array's elements one by one, `f32 sp18; f32 sp1C; … f32 sp38;`, and passes `&sp18` where the game
passed the array. In C those are separate variables: only `sp18` escapes, every store to `sp1C`…`sp38` is dead, and
gcc deletes the arithmetic that fills them. An N64 function compiled to 112 of the game's 183 instructions so, its
whole weighted-sum block gone; another lost a 3×3 matrix fill and kept 51 of 251 (with the arrays back: 77%, then
exact-shaped). The run is the locals of one size at consecutive offsets, typed as its first (`sp` + 4 per `f32`/`s32`), starting at a
local whose address is taken, with no other address taken inside it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stack_run_array'
FAMILIES = (FAMILY,)

SIZES = {'f32': 4, 's32': 4, 'u32': 4, 'M2C_UNK': 4, 'M2C_UNK32': 4, 'f64': 8, 's16': 2, 'u16': 2, 's8': 1, 'u8': 1}
DECL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>' + '|'.join(SIZES) + r')\s+sp(?P<off>[0-9A-Fa-f]+)\s*;[ \t]*\n')


def _runs(decls, escaped):
    """Runs of consecutive offsets of one type, each starting at an escaped local, at least 2 long."""
    by_off = {off: (typ, m) for off, typ, m in decls}
    runs = []
    for off, typ, _ in sorted(decls):
        if off not in escaped:
            continue
        size = SIZES[typ]
        run = [off]
        nxt = off + size
        # (same size, not only the same type: m2c types an element stored 0 as s32 in a run of f32)
        while nxt in by_off and SIZES[by_off[nxt][0]] == size and nxt not in escaped:
            run.append(nxt)
            nxt += size
        if len(run) >= 2:
            runs.append((typ, run))
    return runs


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    decls = [(int(m['off'], 16), m['type'], m) for m in DECL.finditer(body)]
    if len(decls) < 2:
        return []
    escaped = {int(m[1], 16) for m in re.finditer(r'&\s*sp([0-9A-Fa-f]+)\b', body)}
    result = []
    runs = _runs(decls, escaped)
    for chosen in ([*runs], *([r] for r in runs)) if len(runs) > 1 else ([*runs],):
        if not chosen:
            continue
        text = source
        edits = []
        for typ, run in chosen:
            first = run[0]
            first_name = f'sp{first:X}'
            # every name of the run as written in the C (m2c's case)
            names = {}
            for off, t, m in decls:
                if off in run:
                    names[off] = 'sp' + m['off']
            size = SIZES[typ]
            for off, t, m in decls:
                if off == first:
                    edits.append((opening + m.start(), opening + m.end(),
                                  f"{m['indent']}{typ} {names[first]}[{len(run)}];\n"))
                elif off in run:
                    edits.append((opening + m.start(), opening + m.end(), ''))
            for off in run:
                index = (off - first) // size
                for use in re.finditer(r'(?<![\w.>])(&\s*)?' + re.escape(names[off]) + r'\b(?!\s*\[)', body):
                    if DECL.match(body, body.rfind('\n', 0, use.start()) + 1) and \
                            body[body.rfind('\n', 0, use.start()) + 1:use.start()].strip() in SIZES:
                        continue  # the declaration itself
                    at = opening + use.start()
                    if use[1]:
                        written = names[first] if index == 0 else f'&{names[first]}[{index}]'
                    else:
                        written = f'{names[first]}[{index}]'
                    edits.append((at, opening + use.end(), written))
            del first_name
        for a, b, rep in sorted(set(edits), reverse=True):
            text = text[:a] + rep + text[b:]
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result[:4]
