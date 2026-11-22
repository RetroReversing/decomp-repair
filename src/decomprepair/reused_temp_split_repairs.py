"""One temporary the draft reuses for unrelated values, the later use renamed to a local of its own.

m2c keeps one name for each register a binary used, so a temporary can carry a shifted operand in one block and a
difference in a loop far below. The compiler sees one pseudo with the uses and the long life of both, and a priority
that moves its register and its neighbours'. Renamed from its second plain assignment to the one after (or the end), the
second value is a pseudo of its own: 605 -> 435 on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32
-mfp32 -O2`). The opposite of `disjoint_local_merge`, which joins values the draft split. A candidate rewrite; the exact
judge decides.
"""
import re

from . import local_flow
from .allocator_call_guards import dominators
from .integer_repair_support import locals_for, view
from .line_scan import apply, lines, mentions
from .pattern_repairs import close
from .phase_lifetime_repairs import reaching

FAMILY = 'reused_temp_split'
RESTORE_FAMILY = 'switch_temporary_restore'
FAMILIES = (FAMILY, RESTORE_FAMILY)
LIMIT = 8
_LABEL = re.compile(r'(?m)(?:^|[;{}:])\s*([A-Za-z_]\w*)\s*:(?!:)')
_GOTO = re.compile(r'\bgoto\s+([A-Za-z_]\w*)\s*;')


def _restore_switch_writes(source, part, decls):
    """Reconnect an unused generated switch-arm local to the local read after the switch."""
    clean = part.clean
    by_name = {decl['name']: decl for decl in decls}
    switches = []
    for match in re.compile(r'\bswitch\s*\(').finditer(clean, part.opening, part.end):
        condition_end = close(clean, match.end() - 1, '(', ')')
        if not condition_end or not (brace := re.match(r'\s*{', clean[condition_end:])):
            continue
        opening = condition_end + brace.end() - 1
        if end := close(clean, opening, '{', '}'):
            switches.append((opening, end))
    result = []
    if not switches:
        return result
    for name, decl in by_name.items():
        split = re.fullmatch(r'([A-Za-z_]\w*)_b[1-9]\d*_*', name)
        if not split or not (original := by_name.get(split[1])) or original['type'] != decl['type']:
            continue
        use_pattern = re.compile(rf'(?<![\w.>]){name}\b')
        uses = list(use_pattern.finditer(clean, decl.end(), part.end))
        if len(uses) != 1:
            continue
        use = uses[0]
        start = clean.rfind('\n', 0, use.start()) + 1
        if clean[start:use.start()].strip() or not re.match(r'\s*=(?!=)[^;{}]+;\s*break\s*;', clean[use.end():]):
            continue
        enclosing = [(start, end) for start, end in switches if start < use.start() < end]
        if not enclosing:
            continue
        opening, end = enclosing[-1]
        if original.start() >= opening or decl.start() >= opening:
            continue
        other = re.compile(rf'(?<![\w.>]){split[1]}\b')
        arm_write = rf'(?m)^\s*{split[1]}\s*=(?!=)[^;{{}}]+;\s*break\s*;'
        if not (re.search(r'\b(?:case\b[^:]+|default)\s*:', clean[opening:use.start()])
                and re.search(arm_write, clean[opening:end])):
            continue
        later = other.search(clean, end, part.end)
        if not later or re.match(r'\s*=(?!=)', clean[later.end():]):
            continue
        changes = [(decl.start(), decl.end(), ''), (use.start(), use.end(), split[1])]
        result.append((RESTORE_FAMILY, apply(source, changes)))
        if len(result) >= LIMIT:
            break
    return result


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    decls = locals_for(part)
    body = lines(part, source)
    flow = local_flow.analyze(source, name)
    reachable = set(dominators(flow)) if flow else set()
    out = _restore_switch_writes(source, part, decls)
    labels = {label[1]: label.start(1) for label in _LABEL.finditer(part.clean, part.opening, part.end)}
    jumps = [(jump.start(), labels[jump[1]]) for jump in _GOTO.finditer(part.clean, part.opening, part.end)
             if jump[1] in labels]
    if len(out) >= LIMIT:
        return out
    for decl in decls:
        local = decl['name']
        sets = [i for i, l in enumerate(body) if re.match(rf'{re.escape(local)} = ', l.stripped)
                and not mentions(l.stripped.split('=', 1)[1], local)]
        if len(sets) < 2:
            continue
        incoming = reaching(flow, local, reachable) if flow and local in flow.names else {}
        for k in range(1, len(sets)):
            end = sets[k + 1] if k + 1 < len(sets) else len(body)
            fresh = f'{local}_b{k}'
            while re.search(rf'\b{fresh}\b', part.clean):
                fresh += '_'
            start, stop = body[sets[k]].start, body[end - 1].end if end > sets[k] else body[sets[k]].end
            # An incoming goto can skip the write that initializes the new local.
            # A jump to a label before the split still executes that write.
            if any(start < target < stop and not start <= jump < stop for jump, target in jumps):
                continue
            # Every read must keep the same reaching definitions after the rename,
            # including reads at a join reached from another branch and reads
            # outside the textual span fed by a write inside it.
            if not incoming:
                continue
            split_defs = {i for i in reachable if local in flow.nodes[i].defines
                          and start <= flow.nodes[i].start < stop}
            if not split_defs or any(
                (not incoming[i] or not incoming[i] <= split_defs) if start <= node.start < stop
                else bool(incoming[i] & split_defs)
                for i in reachable for node in [flow.nodes[i]] if local in node.uses
            ):
                continue
            span = part.clean[start:stop]
            edits = [(start + m.start(), start + m.end(), fresh) for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', span)]
            # A write with no renamed use can still feed a join after another arm.
            if len(edits) < 2:
                continue
            edits.append((decl.end(), decl.end(), '\n' + (re.match(r'[ \t]*', source[source.rfind('\n', 0, decl.start()) + 1:])[0] or '  ')
                          + f'{decl["type"]} {fresh};'))
            out.append((FAMILY, apply(source, edits)))
            if len(out) >= LIMIT:
                return out
    return out


def guarded_scope_variants(source, name):
    """Combine a safe lifetime split with a one-shot scope around its enclosing guard."""
    result = []
    for family, candidate in variants(source, name):
        if family != FAMILY:
            continue
        part = view(candidate, name)
        if not part or re.search(r'\b(?:goto|volatile|asm|__asm__)\b', part.body):
            continue
        # Restrict to generated split locals; the split itself is checked by
        # variants' reaching-definition proof before this wrapper is offered.
        for decl in locals_for(part):
            split = re.fullmatch(r'([A-Za-z_]\w*)_b[1-9]\d*_*', decl['name'])
            if not split or decl['name'] in source:
                continue
            first = re.search(rf'\b{re.escape(split[1])}\s*=(?!=)', part.body)
            second = re.search(rf'\b{re.escape(decl["name"])}\s*=(?!=)', part.body)
            if not first or not second:
                continue
            first_pos = part.opening + 1 + first.start()
            second_pos = part.opening + 1 + second.start()
            for guard in re.finditer(r'\bif\s*\(', part.clean[part.opening + 1:part.end]):
                start = part.opening + 1 + guard.start()
                prefix = part.clean[part.opening:start]
                if prefix.count('{') - prefix.count('}') != 1:
                    continue
                line_start = part.clean.rfind('\n', part.opening, start) + 1
                if part.clean[line_start:start].strip():
                    continue
                condition_end = close(part.clean, part.opening + guard.end(), '(', ')')
                if not condition_end:
                    continue
                brace = re.match(r'\s*\{', part.clean[condition_end:])
                if not brace:
                    continue
                opening = condition_end + brace.end() - 1
                end = close(part.clean, opening, '{', '}')
                if (not end or not opening < first_pos < second_pos < end
                        or re.match(r'\s*else\b', part.clean[end:])
                        or re.search(r'\b(?:break|continue|return)\b', part.clean[opening:end])):
                    continue
                indent = candidate[line_start:start]
                wrapped = ('do {\n' + candidate[start:end] + '\n' + indent + '} while (0);')
                result.append((FAMILY, candidate[:start] + wrapped + candidate[end:]))
                break
    return list(dict.fromkeys(result))[:8]
