"""A join's tail copied into each arm that reaches it, and the names split per arm, as the game's macros had them.

m2c writes a display-list emission the way the machine code reads, one shared tail after the arms:

    if (c) { var_a0 = D_cursor; D_cursor = var_a0 + 8; var_v1 = a; goto join; }
    else   { var_a0 = D_cursor; ...;                    var_v1 = b;
    join:    *(var_a0 + 4) = var_v1; ... }

The game's source had one command macro per arm, each with its own pointer (`Gfx *g = gp++; g->w0 = ..; g->w1 = ..`),
and GCC 2.7.2 merged the identical tails itself after register allocation (cross-jumping works on hard registers).
With one pointer and one value shared by the arms they are global pseudos, allocated after every local one, so the
cursor took `$a0` where the game's took `$v0` and the constants moved with it. A KMC-compiled N64 function was 810
away; copying the tail into the arms and a pointer of each arm's own was the first of the steps that made it exact
(the others: `phase_union_unshare`, `goto_body_copy`, and the statement order the permuter already tries).

Three families, all offered on the whole function and all proposals the judge decides:

- `arm_private_rename`: a local whose every use inside an if/else arm is reached only by a write inside that arm
  (control-flow liveness, `local_flow`) is renamed to a local declared in the arm. It is one of the `reused_temp_split`
  family's cousins, for arms rather than the text between two writes (a draft's reused name joins arms that the
  compiler then allocates as one value).
- `join_tail_arm_split`: the statement after an if/else, or after a label that arms `goto`, is copied to the end of
  each arm that reaches it (the label moves after it), and the names that become arm-private are renamed in the same
  variant, because the copy alone changes nothing the compiler sees.
- `goto_body_copy`: `if (c) { goto L; }` followed by siblings whose arm holds `L:` gets that arm's body copied in place
  of the `goto` (the game wrote the shared body twice, e.g. `case 1: case 4:` as two macros), so each copy has its own
  constants' uses: a constant held in a saved register across a loop is ranked by how many uses it has.
"""
import re

from . import local_flow
from .allocator_call_guards import dominators
from .integer_repair_support import IDENT, locals_for, refs, view
from .pattern_repairs import close
from .phase_lifetime_repairs import reaching
from .pointer_pair_repairs import POINTER

RENAME_FAMILY = 'arm_private_rename'
TAIL_FAMILY = 'join_tail_arm_split'
COPY_FAMILY = 'goto_body_copy'
UNION_FAMILY = 'phase_union_unshare'
FAMILIES = (RENAME_FAMILY, TAIL_FAMILY, COPY_FAMILY, UNION_FAMILY)

LIMIT = 10
_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'switch', 'return', 'goto', 'break', 'continue', 'case', 'default',
             'sizeof', 'typedef', 'struct', 'union'}
_JUMP = re.compile(r'(?:goto|return|break|continue)\b')


# --- a statement outline: just enough C to find arms, labels and gotos -------------------------------------------------

def _skip(clean, pos, hi):
    while pos < hi and clean[pos].isspace():
        pos += 1
    return pos


def _end(clean, pos, hi):
    """End of the statement starting at `pos`; None when it isn't one this outline understands."""
    if clean[pos] == '{':
        return close(clean, pos, '{', '}')
    keyword = re.match(r'(if|while|for|switch|do)\b', clean[pos:])
    if keyword:
        kind = keyword[1]
        if kind == 'do':
            body = _skip(clean, pos + 2, hi)
            stop = _end(clean, body, hi) if body < hi else None
            tail = re.compile(r'\s*while\s*\(').match(clean, stop) if stop else None
            end = close(clean, tail.end() - 1) if tail else None
            semi = re.compile(r'\s*;').match(clean, end) if end else None
            return semi.end() if semi else None
        opening = clean.find('(', pos)
        stop = close(clean, opening) if opening >= 0 else None
        if not stop:
            return None
        body = _skip(clean, stop, hi)
        end = _end(clean, body, hi) if body < hi else None
        if end and kind == 'if':
            other = _skip(clean, end, hi)
            if re.match(r'else\b', clean[other:]):
                follow = _skip(clean, other + 4, hi)
                end = _end(clean, follow, hi) if follow < hi else None
        return end
    label = re.match(rf'(?!case\b|default\b)({IDENT})\s*:(?!:)', clean[pos:])
    if label:
        return pos + label.end()
    cursor = pos
    while cursor < hi:
        if clean[cursor] in '([':
            stop = close(clean, cursor, clean[cursor], ')' if clean[cursor] == '(' else ']')
            if not stop:
                return None
            cursor = stop
        elif clean[cursor] == ';':
            return cursor + 1
        elif clean[cursor] in '{}':
            return None
        else:
            cursor += 1
    return None


def _items(clean, lo, hi):
    """(start, end) of each statement between `lo` and `hi`, or None when one isn't understood."""
    out, pos = [], _skip(clean, lo, hi)
    while pos < hi:
        end = _end(clean, pos, hi)
        if not end or end > hi:
            return None
        out.append((pos, end))
        pos = _skip(clean, end, hi)
    return out


def _arms(clean, lo, hi, found=None):
    """Interiors (after the `{`, before the `}`) of every braced then/else arm in [lo, hi), nested ones too."""
    found = [] if found is None else found
    items = _items(clean, lo, hi)
    if items is None:
        return None
    for start, end in items:
        text = clean[start:end]
        if text.startswith('{'):
            if _arms(clean, start + 1, end - 1, found) is None:
                return None
        elif re.match(r'if\b', text):
            if not _branches(clean, start, end, found):
                return None
        elif re.match(r'(?:while|for|switch)\b', text):
            opening = clean.find('(', start)
            body = _skip(clean, close(clean, opening), end)
            if clean[body] == '{':
                if _arms(clean, body + 1, end - 1, found) is None:
                    return None
        elif re.match(r'do\b', text):
            body = _skip(clean, start + 2, end)
            stop = _end(clean, body, end)
            if clean[body] == '{' and _arms(clean, body + 1, stop - 1, found) is None:
                return None
    return found


def _branches(clean, start, end, found):
    opening = clean.find('(', start)
    stop = close(clean, opening)
    then = _skip(clean, stop, end)
    then_end = _end(clean, then, end)
    parts = [(then, then_end)]
    other = _skip(clean, then_end, end)
    if re.match(r'else\b', clean[other:]):
        follow = _skip(clean, other + 4, end)
        parts.append((follow, end))
    for first, last in parts:
        if clean[first] == '{':
            found.append((first + 1, last - 1))
            if _arms(clean, first + 1, last - 1, found) is None:
                return False
        elif re.match(r'if\b', clean[first:]):
            if not _branches(clean, first, last, found):
                return False
        elif _arms(clean, first, last, found) is None:
            return False
    return True


def _body(source, name):
    part = view(source, name)
    if not part:
        return None, None, None
    end = close(part.clean, part.opening, '{', '}')
    return (part, end, part.clean) if end else (None, None, None)


# --- arm_private_rename ----------------------------------------------------------------------------------------------

def _declarations(part):
    found = list(locals_for(part))
    found += [d for d in POINTER.finditer(part.clean, part.opening + 1, part.end)
              if part.clean[part.opening + 1:d.start()].rstrip()[-1:] in ('', ';', '{', '}')
              and not re.search(rf'(?<!&)&(?!&)\s*\(*\s*{d["name"]}\b', part.body)
              and len(re.findall(rf'\b{d["name"]}\b', part.clean[:part.opening])) == 0]
    unique = {}
    for d in found:
        shadows = [m for m in re.finditer(rf'\b({IDENT})(?:\s+\**\s*|\s*\*+\s*){re.escape(d["name"])}\s*(?=[;=,\[])', part.body)
                   if m[1] not in _KEYWORDS]
        if len(shadows) == 1:
            unique.setdefault(d['name'], d)
    return list(unique.values())


def _fresh(name, clean, taken, tag='a'):
    k = 1
    while True:
        candidate = f'{name}_{tag}{k}'
        if candidate not in taken and not re.search(rf'\b{candidate}\b', clean):
            taken.add(candidate)
            return candidate
        k += 1


def _type_text(decl):
    kind = re.sub(r'\s*(\*+)$', r' \1', decl['type'].strip())
    return kind if kind.endswith('*') else kind + ' '


def _private_regions(source, name, only=None):
    """{local name: [(lo, hi), ...]}: the minimal arms in which that local is private."""
    part, end, clean = _body(source, name)
    if not part:
        return None
    declarations = _declarations(part)
    flow = local_flow.analyze(source, name, declarations=declarations)
    arms = _arms(clean, part.opening + 1, end - 1)
    if flow is None or not arms:
        return None
    reachable = set(dominators(flow))
    found = {}
    for decl in declarations:
        variable = decl['name']
        if only and variable not in only:
            continue
        mentions = [m.start() for m in refs(part, decl)]
        if len(mentions) < 2 or variable not in flow.names:
            continue
        incoming = reaching(flow, variable, reachable)
        ok = []
        for lo, hi in arms:
            if not any(lo <= m < hi for m in mentions):
                continue
            inside = {i for i in reachable if variable in flow.nodes[i].defines and lo <= flow.nodes[i].start < hi}
            if not inside:
                continue
            good = True
            for i in reachable:
                node = flow.nodes[i]
                if variable not in node.uses:
                    continue
                if lo <= node.start < hi:
                    good = bool(incoming[i]) and incoming[i] <= inside
                elif incoming[i] & inside:
                    good = False
                if not good:
                    break
            if good:
                ok.append((lo, hi))
        # minimal arms: drop an arm that contains another accepted one
        minimal = [a for a in ok if not any(b != a and a[0] <= b[0] and b[1] <= a[1] for b in ok)]
        covered = [m for m in mentions if any(lo <= m < hi for lo, hi in minimal)]
        if minimal and (len(minimal) > 1 or len(covered) < len(mentions)):
            found[variable] = (decl, minimal, len(covered) == len(mentions))
    return found


def _apply_rename(source, name, found):
    part, end, clean = _body(source, name)
    edits, taken = [], set()
    for variable, (decl, regions, everything) in found.items():
        for lo, hi in regions:
            fresh = _fresh(variable, clean, taken)
            for hit in re.finditer(rf'(?<![\w.>]){re.escape(variable)}\b(?!\s*:(?!:))', clean[lo:hi]):
                edits.append((lo + hit.start(), lo + hit.end(), fresh))
            following = re.compile(r'\s*').match(clean, lo).end()
            indent = ' ' * (following - (clean.rfind('\n', 0, following) + 1))
            edits.append((lo, lo, f'\n{indent}{_type_text(decl)}{fresh};'))
        if everything:
            line = source[source.rfind('\n', 0, decl.start()) + 1:source.find('\n', decl.end()) + 1]
            if line.strip() == source[decl.start():decl.end()].strip():
                edits.append((source.rfind('\n', 0, decl.start()) + 1, source.find('\n', decl.end()) + 1, ''))
    for start, stop, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def rename_variants(source, name):
    """One variant per arm (every local private to it renamed there), then all arms at once."""
    found = _private_regions(source, name)
    if not found:
        return []
    by_arm = {}
    for variable, (decl, regions, _) in found.items():
        for region in regions:
            by_arm.setdefault(region, []).append(variable)
    out = []
    for region in sorted(by_arm):
        pick = {variable: (found[variable][0], [region], False) for variable in by_arm[region]}
        out.append((RENAME_FAMILY, _apply_rename(source, name, pick)))
        if len(out) >= LIMIT:
            break
    if len(by_arm) > 1:
        out.append((RENAME_FAMILY, _apply_rename(source, name, found)))
    return [(family, text) for family, text in out if text != source]


# --- phase_union_unshare ---------------------------------------------------------------------------------------------

def union_variants(source, name):
    """A function-local `union { T *a; U b; } u;` whose uses are all `u.a` / `u.b`, as one local per member."""
    part, end, clean = _body(source, name)
    if not part:
        return []
    out = []
    for union in re.finditer(rf'(?m)^([ \t]*)union\s*{{([^{{}}]*)}}\s*({IDENT})\s*;[ \t]*\n', clean[:end]):
        if union.start() < part.opening:
            continue
        variable = union[3]
        members = [(re.sub(r'\s*(\*+)$', r' \1', kind.strip()), member)
                   for kind, member in re.findall(rf'([^;{{}}]*?)\b({IDENT})\s*;', union[2])]
        rest = clean[union.end():end]
        if not members or not re.search(rf'\b{variable}\b', rest):
            continue
        if any(not re.match(r'\s*\.\s*\w+', rest[m.end():]) for m in re.finditer(rf'\b{variable}\b', rest)):
            continue
        declarations = ''.join(f'{union[1]}{kind}{" " if not kind.endswith("*") else ""}{variable}_{member};\n'
                               for kind, member in members)
        text = source[:union.start()] + declarations + source[union.end():]
        names = '|'.join(re.escape(member) for _, member in members)
        out.append((UNION_FAMILY, re.sub(rf'\b{variable}\s*\.\s*({names})\b', rf'{variable}_\1', text)))
    return out


# --- join_tail_arm_split ---------------------------------------------------------------------------------------------

_CALL = re.compile(rf'\b(?!sizeof\b){IDENT}\s*\(|\+\+|--')


def _blocks(clean, lo, hi, found=None):
    """(lo, hi, items) for the function body and every braced block inside it."""
    found = [] if found is None else found
    items = _items(clean, lo, hi)
    if items is None:
        return None
    found.append((lo, hi, items))
    for start, end in items:
        for opening in _sub_blocks(clean, start, end):
            if _blocks(clean, opening[0] + 1, opening[1] - 1, found) is None:
                return None
    return found


def _sub_blocks(clean, start, end):
    """The braced blocks directly below one statement (an `if`'s arms, a loop's body, a bare block)."""
    text = clean[start:end]
    if text.startswith('{'):
        return [(start, end)]
    found = []
    if re.match(r'if\b', text):
        opening = clean.find('(', start)
        then = _skip(clean, close(clean, opening), end)
        then_end = _end(clean, then, end)
        pieces = [(then, then_end)]
        other = _skip(clean, then_end, end)
        if re.match(r'else\b', clean[other:]):
            pieces.append((_skip(clean, other + 4, end), end))
        for first, last in pieces:
            if clean[first] == '{':
                found.append((first, last))
            elif re.match(r'if\b', clean[first:]):
                found += _sub_blocks(clean, first, last)
    elif re.match(r'(?:while|for|switch)\b', text):
        opening = clean.find('(', start)
        body = _skip(clean, close(clean, opening), end)
        if clean[body] == '{':
            found.append((body, end))
    elif re.match(r'do\b', text):
        body = _skip(clean, start + 2, end)
        if clean[body] == '{':
            found.append((body, _end(clean, body, end)))
    return found


def _plain(clean, start, end):
    text = clean[start:end]
    return (text.endswith(';') and not text.startswith(';') and '{' not in text and not _CALL.search(text)
            and not re.match(rf'(?:{"|".join(sorted(_KEYWORDS))})\b', text) and not re.match(rf'{IDENT}\s*:(?!:)', text))


def _label(clean, start, end):
    hit = re.fullmatch(rf'(?!case\b|default\b)({IDENT})\s*:', clean[start:end])
    return hit[1] if hit else None


def _falls_out(clean, lo, hi):
    items = _items(clean, lo, hi)
    return items is not None and not (items and _JUMP.match(clean[items[-1][0]:items[-1][1]]))


def _gotos(clean, part, label):
    return [m for m in re.finditer(rf'\bgoto\s+{re.escape(label)}\s*;', clean[part.opening:])]


def _cut(source, start, stop):
    """The edit removing a statement, with its line when it has the line to itself."""
    first = source.rfind('\n', 0, start) + 1
    last = source.find('\n', stop)
    if not source[first:start].strip() and last >= 0 and not source[stop:last].strip():
        return (first, last + 1, '')
    return (start, stop, '')


def _append(source, clean, lo, hi, text):
    """The edit adding a statement at the end of the block between lo and hi, indented like its last statement."""
    items = _items(clean, lo, hi)
    line = source.rfind('\n', 0, items[-1][0] if items else lo) + 1
    indent = re.match(r'[ \t]*', source[line:])[0] if items else '  '
    close_line = source.rfind('\n', 0, hi) + 1
    if not source[close_line:hi].strip():
        return (close_line, close_line, f'{indent}{text}\n')
    return (hi, hi, f'\n{indent}{text}\n')


def _unwrap_arms(source, name, mark):
    """The one-shot `do { X } while (0);` and bare `{ X }` wrappers dropped inside every arm that declares a local
    whose name `mark` matches. A wrapper is a scheduling fence (and a loop to loop.c: an address loaded in two of
    them is hoisted out of the whole loop), which an arm of the game's macros never had."""
    part, end, clean = _body(source, name)
    blocks = _blocks(clean, part.opening + 1, end - 1) if part else None
    if not blocks:
        return source
    edits = []

    def walk(lo, hi):
        for start, stop in _items(clean, lo, hi) or []:
            text = clean[start:stop]
            wrapper = re.fullmatch(r'do\s*({.*})\s*while\s*\(\s*0\s*\)\s*;', text, re.S) or (
                re.fullmatch(r'({.*})', text, re.S))
            if wrapper:
                opening = start + wrapper.start(1)
                inner = _items(clean, opening + 1, start + wrapper.end(1) - 1)
                if inner is not None and not any(
                        _label(clean, *i) or re.match(r'(?:break|continue|case|default|return)\b', clean[i[0]:i[1]])
                        or re.match(rf'(?:[su]\d+|int|void|f32|{IDENT})\s+\**\s*{IDENT}\s*;', clean[i[0]:i[1]]) for i in inner):
                    edits.append((start, stop, source[opening + 1:start + wrapper.end(1) - 1].strip()))
                    continue
            for a, b in _sub_blocks(clean, start, stop):
                walk(a + 1, b - 1)

    for lo, hi, items in blocks[1:]:
        if items and re.match(rf'[\w ]+\*?\s*{mark}\d*;', clean[items[0][0]:items[0][1]]):
            walk(lo, hi)
    for start, stop, text in sorted(set(edits), reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def tail_variants(source, name):
    part, end, clean = _body(source, name)
    if not part:
        return []
    blocks = _blocks(clean, part.opening + 1, end - 1)
    if not blocks:
        return []
    out = []
    for lo, hi, items in blocks:
        for k in range(len(items) - 1):
            first, second = items[k], items[k + 1]
            if not _plain(clean, *second):
                continue
            tail = source[second[0]:second[1]]
            names = set(re.findall(IDENT, clean[second[0]:second[1]]))
            edits = None
            if re.match(r'if\b', clean[first[0]:first[1]]):
                arms = _sub_blocks(clean, *first)
                opening = clean.find('(', first[0])
                then = _skip(clean, close(clean, opening), first[1])
                has_else = re.search(r'\belse\b', clean[_end(clean, then, first[1]):first[1]]) is not None
                if len(arms) != 2 or not has_else or not any(_falls_out(clean, a + 1, b - 1) for a, b in arms):
                    continue
                edits = [_cut(source, *second)]
                for a, b in arms:
                    if _falls_out(clean, a + 1, b - 1):
                        edits.append(_append(source, clean, a + 1, b - 1, tail))
            elif (label := _label(clean, *first)):
                jumps = _gotos(clean, part, label)
                if not jumps:
                    continue
                after = _skip(clean, second[1], hi)
                edits = [(first[0], second[0], ''), (second[1], second[1], f'\n{label}:' + (' ;' if after >= hi else ''))]
                for jump in jumps:
                    at = part.opening + jump.start()
                    before = clean[:at].rstrip()
                    if before[-1:] in '{};:' or before.endswith(')') is False and before[-1:] in ';{}':
                        edits.append((at, at, f'{tail} '))
                    else:
                        edits.append((at, part.opening + jump.end(), f'{{ {tail} {jump[0]} }}'))
            if not edits:
                continue
            text = source
            for start, stop, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
                text = text[:start] + replacement + text[stop:]
            if text == source:
                continue
            found = _private_regions(text, name, only=names)
            combined = _apply_rename(text, name, found) if found else None
            if combined and combined != text:
                out.append((TAIL_FAMILY, combined))
                if (bare := _unwrap_arms(combined, name, r'\w+_a')) != combined:
                    out.append((TAIL_FAMILY, bare))
    # only a copy whose names also became arm-private changes what the compiler allocates; the bare copy is the same pseudo
    return out[:LIMIT]


# --- goto_body_copy --------------------------------------------------------------------------------------------------

def copy_variants(source, name):
    """`if (c) { goto L; }` then siblings holding `L:` in an arm: the arm's body copied where the goto was."""
    part, end, clean = _body(source, name)
    if not part:
        return []
    blocks = _blocks(clean, part.opening + 1, end - 1)
    if not blocks:
        return []
    out = []
    for lo, hi, items in blocks:
        for k, (start, stop) in enumerate(items):
            jump = re.fullmatch(rf'if\s*\([^;{{}}]*\)\s*{{\s*goto\s+({IDENT})\s*;\s*}}', clean[start:stop])
            if not jump:
                continue
            label = jump[1]
            for j in range(k + 1, len(items)):
                target = None
                if re.match(r'if\b', clean[items[j][0]:items[j][1]]):
                    for a, b in _sub_blocks(clean, *items[j]):
                        inner = _items(clean, a + 1, b - 1)
                        if inner and any(_label(clean, *item) == label for item in inner):
                            target = (a, b, inner)
                            break
                if not target:
                    continue
                a, b, inner = target
                labels = [item for item in inner if _label(clean, *item)]
                if len(_gotos(clean, part, label)) != 1 or any(
                        re.search(rf'\bgoto\s+{_label(clean, *item)}\b', clean[a:b]) for item in labels if item):
                    break
                first = next(item for item in labels if _label(clean, *item) == label)
                # other labels in the arm stay with the original (jumped to from elsewhere); the copy has none
                body = ''
                cursor = a + 1
                for item in labels:
                    body += source[cursor:item[0]]
                    cursor = item[1]
                body += source[cursor:b - 1]
                opening = clean.find('{', start)
                replaced = source[:opening] + '{' + body + '}' + source[stop:]
                # the label is gone from the arm; the body now runs in the goto's place and the siblings between
                # the `if` and the arm's statement become its else
                shift = len(replaced) - len(source)
                inner_start, inner_stop = items[k + 1][0] + shift, items[j][1] + shift
                text = replaced[:inner_start] + 'else {\n' + replaced[inner_start:inner_stop] + '\n}' + replaced[inner_stop:]
                label_at = text.find(source[first[0]:first[1]], inner_start)
                text = text[:label_at] + text[label_at + (first[1] - first[0]):]
                out.append((COPY_FAMILY, text))
                break
            if len(out) >= LIMIT:
                return out
    return out


def variants(source, name):
    """Every family of this module on one function.

    The union's split alone is worse (the members are two locals the draft used as one storage); it pays off once an
    arm's names are private (810 -> 730 on the function above), so each split is also offered with every arm rename."""
    unions = union_variants(source, name)
    combined = [(UNION_FAMILY, renamed) for _, split in unions for _, renamed in rename_variants(split, name)]
    return (combined + unions + rename_variants(source, name) + tail_variants(source, name)
            + copy_variants(source, name))
