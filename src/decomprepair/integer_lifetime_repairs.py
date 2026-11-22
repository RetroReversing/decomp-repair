"""Bounded integer lifetime splits and non-overlapping merges for old register allocators.

No address-taken variable is rewritten. Loops, shadowing and incoming jumps are boundaries, not reasons
to guess liveness from textual order. The ordinary judge still decides every generated hypothesis.
"""
import re

from . import local_flow
from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .pattern_repairs import close


def depth(text, end):
    return text[:end].count('{')-text[:end].count('}')


def loop_ranges(part):
    ranges = []
    for hit in re.finditer(r'\b(for|while|do)\b', part.clean[part.opening:part.end]):
        start = part.opening+hit.start()
        pos = part.opening+hit.end()
        if hit[1] != 'do':
            opening = part.clean.find('(', pos)
            pos = close(part.clean, opening) if opening >= 0 else None
        if pos is None:
            continue
        while pos < part.end and part.clean[pos].isspace():
            pos += 1
        end = close(part.clean, pos, '{', '}') if part.clean[pos:pos+1] == '{' else part.clean.find(';', pos)+1
        if end and end > pos:
            ranges.append((start, end))
    return ranges


def jump_crosses(part, start, end):
    labels = {hit[1]: hit.start() for hit in re.finditer(rf'\b({IDENT})\s*:(?!:)', part.clean)}
    for jump in re.finditer(rf'\bgoto\s+({IDENT})\s*;', part.clean):
        target = labels.get(jump[1])
        if target is None:
            return True
        if (start <= jump.start() < end) != (start <= target < end):
            return True
    return False


def counter_reuse_variants(source, name):
    """An integer temporary that is dead before a loop starts, renamed to the loop's own counter (IDO, GCC 2.x).

    The allocators colour a variable as one web: a one-use flag read at the top of a function and the counter of a
    loop further down are two variables, two sets of uses, and the flag takes a register the counter's constants
    could have had. The original source often used one variable for both (`i`), so the flag's register came from the
    counter's web instead. An IDO bit-stream reader read its first flag into its own local, and the target's flag
    sat in `$t3` and the constant it compared with in `$a0`, the reverse of the draft's: reading the flag into the
    loop counter made the function exact (the flag's declaration stays, unused: IDO still reserves its word of frame,
    and the target's frame had it).

    Only a plain local of the counter's type whose every use lies before the counter's first mention, where the
    counter's first mention assigns it (`i = 0`, a `for (i = 0; ...)` initialiser), so the old value is never read.
    The flag's declaration is kept: the proposal changes who owns the register, not how much frame there is.
    """
    part = view(source, name)
    if not part:
        return []
    loops = loop_ranges(part)
    if not loops:
        return []
    declarations = [decl for decl in locals_for(part) if depth(part.clean, decl.start()) == depth(part.clean, part.opening)+1]
    active = [(decl, refs(part, decl)) for decl in declarations]
    active = [(decl, hits) for decl, hits in active if hits]
    result = []
    for counter, counter_refs in active:
        first = counter_refs[0]
        if not re.match(r'\s*=(?!=)', part.clean[first.end():]) or not any(a <= first.start() < b for a, b in loops):
            continue
        for temp, temp_refs in active:
            if (temp is counter or temp['type'] != counter['type'] or temp_refs[-1].end() > first.start()
                    or any(a <= hit.start() < b for hit in temp_refs for a, b in loops)
                    or jump_crosses(part, temp_refs[0].start(), first.start())):
                continue
            # Several definitions of a flag are fine; a flag read again after the loop starts is not.
            edits = [(hit.start(), hit.end(), counter['name']) for hit in temp_refs]
            result.append(('merge_integer_lifetimes', edit(source, edits)))
            if len(result) >= 4:
                return result
    return result


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    loops = loop_ranges(part)
    declarations = [decl for decl in locals_for(part) if depth(part.clean, decl.start()) == depth(part.clean, part.opening)+1]
    active = [(decl, refs(part, decl)) for decl in declarations]
    active = [(decl, hits) for decl, hits in active if hits]
    result = []
    # Splitting an independent top-level definition preserves every evaluation and update in its segment.
    for decl, hits in active:
        variable = decl['name']
        definitions = []
        for hit in hits:
            definition = re.match(r'\s*=(?!=)([^;{}]*);', part.clean[hit.end():])
            prefix = part.clean[part.opening+1:hit.start()].rstrip()
            if (definition and not re.search(rf'\b{re.escape(variable)}\b', definition[1])
                    and prefix[-1:] in {';', '}'} and depth(part.clean, hit.start()) == depth(part.clean, decl.start())
                    and not any(a <= hit.start() < b for a, b in loops)):
                definitions.append(hit)
        for index, definition in enumerate(definitions[1:3], 1):
            stop = definitions[index+1].start() if index+1 < len(definitions) else part.end-1
            if jump_crosses(part, definition.start(), stop):
                continue
            fresh = f'__repair_{variable}_{index}'
            if re.search(rf'\b{fresh}\b', part.clean):
                continue
            edits = [(decl.end(), decl.end(), f'\n    {decl["type"]} {fresh};')]
            edits += [(hit.start(), hit.end(), fresh) for hit in hits if definition.start() <= hit.start() < stop]
            result.append(('split_integer_lifetime', edit(source, edits)))
        if len(result) >= 4:
            break
    pairs = []
    for left, left_refs in active:
        for right, right_refs in active:
            if left['type'] != right['type'] or left_refs[-1].end() >= right_refs[0].start():
                continue
            start, end = left_refs[0].start(), right_refs[-1].end()
            region = part.clean[start:end]
            if re.search(r'\b(?:for|while|do|goto|case|default|break|continue)\b', region):
                continue
            if any(a <= start < b or a <= right_refs[0].start() < b for a, b in loops) or jump_crosses(part, start, end):
                continue
            if not re.match(r'\s*=(?!=)', part.clean[right_refs[0].end():]):
                continue
            # Scope crossings through if arms are fine; a declaration's scope and type stay unchanged.
            same_stem = re.sub(r'_\d+$', '', left['name']) == re.sub(r'_\d+$', '', right['name'])
            pairs.append((not same_stem, right_refs[0].start()-left_refs[-1].end(), left, right, right_refs))
    for _, _, left, right, hits in sorted(pairs, key=lambda pair: pair[:2])[:6]:
        edits = [(right.start(), right.end(), '')]+[(hit.start(), hit.end(), left['name']) for hit in hits]
        result.append(('merge_integer_lifetimes', edit(source, edits)))
    result += counter_reuse_variants(source, name)
    # A CFG can prove disjoint lifetimes even when loops/gotos prevent the textual shortcut.
    flow = local_flow.analyze(source, name)
    if flow:
        safe = {decl['name'] for decl in flow.locals}
        for left, left_refs in active:
            for right, right_refs in active:
                if (left['name'] >= right['name'] or left['name'] not in safe or right['name'] not in safe
                        or left['type'] != right['type'] or not local_flow.disjoint(flow, left, right)):
                    continue
                edits = [(right.start(), right.end(), '')]+[(hit.start(), hit.end(), left['name']) for hit in right_refs]
                candidate = edit(source, edits)
                if all(text != candidate for _, text in result):
                    result.append(('cfg_integer_lifetimes', candidate))
                if sum(family == 'cfg_integer_lifetimes' for family, _ in result) >= 6:
                    return list(dict.fromkeys(result))
    return list(dict.fromkeys(result))
