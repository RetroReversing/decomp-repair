"""The shapes that let GCC 2.x spill ordinary locals the way an original function did, instead of hiding them in volatiles.

A draft that matched in everything but its stack slots usually carries a workaround from an earlier search: a local
struct of `volatile` fields that holds the parameters and flags the target keeps in memory, `volatile` reads of a
parameter, a duplicated `else` arm that only exists to keep a variable alive. Each of those makes the compiler load
the value into a register it picks by its normal rules (`$v0`) while the target reloads a spilled pseudo into the
reload register it picks (`$t0`): a function of 363 instructions stood at 1025 with the struct and at 0 once the same
values were plain locals and four small shapes were set (the chain is in docs/COMPILER_MATCHING_LEARNINGS.md of
decompdecomp). The families, each one candidate rewrite for the exact judge:

- `volatile_read_drop`: `*(volatile T *)&x` read as the plain `x`.
- `volatile_state_unwrap`: a local struct whose fields are only read and written as `NAME.field` becomes one plain
  local per used field (volatile dropped, in field order: the order GCC numbers the pseudos decides which spill slot
  each gets), and a field assigned once from a parameter that is never written is that parameter.
- `narrow_copy_merge`: `a = p; ... b = (s8) a;` with nothing else using `a` becomes `b = (s8) p;`.
- `identical_arm_collapse`: `if (x) A else if (y) B else B` keeps one `B`.
- `flag_exit_mask_test`: a byte flag that ends a `do` loop (`while (!f)`, `while (f == 0)`) tested as
  `(f & 1) == 0`; the compiler then copies the reloaded byte with a `move` where the plain test reloads straight into
  the register of the branch.
- `preloop_assignment_swap`: two independent one-line assignments directly before a `do` loop, swapped. The loop
  optimizer emits what it hoists after them and the first scheduler breaks ties by that order, so which of the two
  the target computes first decides where a hoisted constant lands.
- `loop_constant_stage`: a float literal repeated inside a `do` loop becomes a local assigned just before the run of
  statements that precedes the loop, so the hoisted constant is scheduled ahead of them.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import declaration_end

FAMILIES = ('volatile_read_drop', 'volatile_state_unwrap', 'narrow_copy_merge', 'identical_arm_collapse',
            'flag_exit_mask_test', 'loop_constant_stage', 'preloop_assignment_swap')
_TYPE = r'(?:unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int)|[su](?:8|16|32|64)|f32|f64|char|short|int|float|double|long)'


def _parameters(part):
    head = part.clean[:part.opening]
    inner = head[head.rfind('(') + 1:head.rfind(')')]
    names = []
    for argument in inner.split(','):
        found = re.findall(IDENT, argument)
        if found and found[-1] != 'void':
            names.append(found[-1])
    return names


def _written(text, name):
    return bool(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|[&]\s*{re.escape(name)}\b'
                          rf'|(?:\+\+|--)\s*{re.escape(name)}\b|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', text))


def _count(text, name):
    return len(re.findall(rf'(?<![\w.>]){re.escape(name)}\b', text))


def _fresh(part, base):
    name, n = base, 1
    while re.search(rf'\b{re.escape(name)}\b', part.clean):
        n += 1
        name = f'{base}{n}'
    return name


def volatile_read_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    pattern = re.compile(rf'\*\s*\(\s*volatile\s+{_TYPE}\s*\*\s*\)\s*&\s*({IDENT})\b')
    hits = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if not hits:
        return []
    return [('volatile_read_drop', edit(source, [(h.start(), h.end(), h[1]) for h in hits]))]


def _struct(part):
    """(start, end, fields, variable) of the first local `struct { ... } NAME;` of scalar fields, or None."""
    found = _structs(part)
    return found[0] if found else None


def _structs(part):
    """Every local `struct { ... } NAME;` of scalar fields, a `volatile` before `struct` or before `NAME` included."""
    out = []
    for hit in re.finditer(r'(?:\bvolatile\s+)?\bstruct\s*\{', part.clean):
        if hit.start() < part.opening:
            continue
        depth, pos = 0, hit.end() - 1
        while pos < part.end:
            depth += part.clean[pos] == '{'
            depth -= part.clean[pos] == '}'
            if depth == 0:
                break
            pos += 1
        tail = re.match(rf'\s*(?:volatile\s+)?({IDENT})\s*;', part.clean[pos + 1:part.end])
        if not tail:
            continue
        fields = []
        for field in part.clean[hit.end():pos].split(';'):
            field = field.strip()
            if not field:
                continue
            decl = re.fullmatch(rf'(?P<q1>(?:volatile\s+)?)(?P<type>{_TYPE}|{IDENT}\s*\*+)\s*(?P<q2>(?:volatile\s+)?)'
                                rf'(?P<name>{IDENT})(?P<array>\[[^\]]*\])?', field)
            if not decl:
                fields = None
                break
            fields.append(decl)
        if fields:
            out.append((hit.start(), pos + 1 + tail.end(), fields, tail[1]))
    return out


def state_unwrap_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for found in _structs(part):
        out += _unwrap_state(source, part, found)
    return out


def _unwrap_state(source, part, found):
    start, end, fields, var = found
    body = part.clean[end:part.end]
    if re.search(rf'(?<![\w.>])&?\s*{re.escape(var)}\b(?!\s*\.)', body):
        return []
    used = [f for f in fields if not f['array'] and re.search(rf'\b{re.escape(var)}\s*\.\s*{re.escape(f["name"])}\b', body)]
    if not used or any(f['array'] for f in fields if re.search(rf'\b{re.escape(var)}\s*\.\s*{re.escape(f["name"])}\b', body)):
        return []
    params = _parameters(part)
    edits, declarations, replaced, removed = [], [], {}, []
    for field in used:
        member = field['name']
        first = re.search(rf'\b{re.escape(var)}\s*\.\s*{re.escape(member)}\s*=\s*(?P<value>{IDENT})\s*;', body)
        writes = len(re.findall(rf'\b{re.escape(var)}\s*\.\s*{re.escape(member)}\s*=(?!=)', body))
        if first and first['value'] in params and writes == 1 and not _written(body, first['value']):
            replaced[member] = first['value']
            line = body.rfind('\n', 0, first.start()) + 1
            after = body.find('\n', first.end()) + 1
            removed.append((end + line, end + after))
            continue
        local = _fresh(part, f'{var}_{member}')
        replaced[member] = local
        declarations.append(f'{field["type"]} {local};')
    for hit in re.finditer(rf'\b{re.escape(var)}\s*\.\s*({IDENT})\b', body):
        if hit[1] in replaced and not any(a <= end + hit.start() < b for a, b in removed):
            edits.append((end + hit.start(), end + hit.end(), replaced[hit[1]]))
    edits += [(a, b, '') for a, b in removed]
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
    edits.append((start, end, ('\n' + indent).join(declarations)))
    revised = edit(source, edits)
    return [('volatile_state_unwrap', re.sub(r'\n[ \t]*\n(?=[ \t]*\n)', '\n', revised))]


def narrow_copy_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    params = _parameters(part)
    out = []
    for first in re.compile(rf'(?m)^[ \t]*(?P<tmp>{IDENT})\s*=\s*(?P<src>{IDENT})\s*;[ \t]*\n').finditer(part.clean, part.opening + 1):
        tmp, src = first['tmp'], first['src']
        if src not in params or _written(part.clean[part.opening:part.end], src) or _count(part.clean[part.opening:part.end], tmp) not in (2, 3):
            continue
        use = re.search(rf'(?m)^(?P<lead>[ \t]*(?:{IDENT}\s*=\s*)?)\(\s*(?:s8|u8|s16|u16|char|short)\s*\)\s*{re.escape(tmp)}\s*;',
                        part.clean[first.end():part.end])
        if not use:
            continue
        cast = re.search(rf'\(\s*(?:s8|u8|s16|u16|char|short)\s*\)\s*{re.escape(tmp)}', part.clean[first.end() + use.start():])
        a, b = first.end() + use.start() + cast.start(), first.end() + use.start() + cast.end()
        revised = edit(source, [(first.start(), first.end(), ''), (a, b, source[a:b].replace(tmp, src))])
        decl = re.search(rf'(?m)^[ \t]*(?:register\s+)?{_TYPE}\s+{re.escape(tmp)}\s*;[ \t]*\n', revised)
        if decl:
            revised = revised[:decl.start()] + revised[decl.end():]
        out.append(('narrow_copy_merge', revised))
    return out[:1]


def arm_collapse_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    pattern = re.compile(r'(?m)^(?P<i>[ \t]*)else\s*\n(?P=i)[ \t]*if\s*\((?P<cond>[^\n]*)\)\s*\n'
                         r'(?P<a>[ \t]*\{[^{}]*\}[ \t]*)\n(?P=i)[ \t]*else\s*\n(?P<b>[ \t]*\{[^{}]*\}[ \t]*)\n')
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        if re.sub(r'\s+', ' ', hit['a']).strip() == re.sub(r'\s+', ' ', hit['b']).strip():
            return [('identical_arm_collapse', edit(source, [(hit.start(), hit.end(), f'{hit["i"]}else\n{source[hit.start("b"):hit.end("b")]}\n')]))]
    return []


def flag_test_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for flag in re.findall(rf'\b(?:u8|unsigned\s+char)\s+({IDENT})\s*;', part.clean[part.opening:part.end]):
        if not re.search(rf'(?<![\w.>]){flag}\s*=\s*0\s*;', part.clean) or not re.search(rf'(?<![\w.>]){flag}\s*=\s*1\s*;', part.clean):
            continue
        if re.search(rf'(?<![\w.>]){flag}\s*=(?!=)(?!\s*[01]\s*;)', part.clean) or re.search(rf'&\s*{flag}\b', part.clean):
            continue
        for hit in re.finditer(rf'\bwhile\s*\(\s*(?:!\s*{flag}|{flag}\s*==\s*0)\s*\)\s*;', part.clean[part.opening:part.end]):
            a = part.opening + hit.start()
            out.append(('flag_exit_mask_test', edit(source, [(a, part.opening + hit.end(), f'while (({flag} & 1) == 0);')])))
    return out[:1]


def _stage(source, name):
    part = view(source, name)
    if not part:
        return []
    end = declaration_end(part)
    loops = list(re.compile(r'(?m)^[ \t]*do[ \t]*\n[ \t]*\{').finditer(part.clean, part.opening, part.end))
    for loop in loops:
        depth, pos = 0, loop.end() - 1
        while pos < part.end:
            depth += part.clean[pos] == '{'
            depth -= part.clean[pos] == '}'
            if depth == 0:
                break
            pos += 1
        if not re.match(r'\s*while\s*\(', part.clean[pos + 1:part.end]):
            continue
        body = part.clean[loop.end():pos]
        literals = [m for m in re.finditer(r'(?<![\w.])\d+\.\d+f\b', body) if m[0] not in ('0.0f',)]
        by = {}
        for m in literals:
            by.setdefault(m[0], []).append(m)
        repeated = [k for k, v in by.items() if len(v) >= 2]
        if len(repeated) != 1 or not end:
            continue
        literal = repeated[0]
        # the contiguous run of one-line assignments right before the loop
        pos = loop.start()
        run = pos
        while True:
            prev = part.clean.rfind('\n', 0, run - 1)
            line = part.clean[prev + 1:run].strip()
            if re.fullmatch(rf'{IDENT}\s*=\s*[^;{{}}]*;', line):
                run = prev + 1
            else:
                break
        if run == pos:
            continue
        local = _fresh(part, 'repair_loop_scale')
        indent = re.match(r'[ \t]*', source[run:])[0]
        edits = [(loop.end() + m.start(), loop.end() + m.end(), local) for m in by[literal]]
        edits.append((run, run, f'{indent}{local} = {literal};\n'))
        edits.append((end, end, f'\n  f32 {local};'))
        return [('loop_constant_stage', edit(source, edits))]
    return []


def preloop_swap_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for loop in re.compile(r'(?m)^[ \t]*do[ \t]*\n[ \t]*\{').finditer(part.clean, part.opening, part.end):
        lines, run = [], loop.start()
        while True:
            prev = part.clean.rfind('\n', 0, run - 1)
            line = part.clean[prev + 1:run]
            hit = re.fullmatch(rf'[ \t]*({IDENT})\s*=\s*([^;{{}}]*);[ \t]*\n?', line)
            if not hit or prev < part.opening:
                break
            lines.append((prev + 1, run, hit[1], hit[2]))
            run = prev + 1
        lines.reverse()
        for (a1, b1, w1, r1), (a2, b2, w2, r2) in zip(lines, lines[1:]):
            if b1 != a2 or re.search(rf'(?<![\w.>]){w1}\b', r2) or re.search(rf'(?<![\w.>]){w2}\b', r1) or w1 == w2:
                continue
            if re.search(r'[A-Za-z_]\w*\s*\(', r1) or re.search(r'[A-Za-z_]\w*\s*\(', r2):
                continue
            out.append(('preloop_assignment_swap', edit(source, [(a1, b2, source[a2:b2] + source[a1:b1])])))
    return out


def constant_stage_variants(source, name):
    """The staged constant alone and, since the two only pay off together, with each swap of the run before the loop."""
    out = _stage(source, name)
    for _, swapped in preloop_swap_variants(source, name):
        out += _stage(swapped, name)
    return out


def variants(source, name):
    out = []
    for build in (volatile_read_variants, state_unwrap_variants, narrow_copy_variants, arm_collapse_variants,
                  flag_test_variants, preloop_swap_variants, constant_stage_variants):
        try:
            out += build(source, name)
        except (AttributeError, IndexError, TypeError):
            continue
    return out
