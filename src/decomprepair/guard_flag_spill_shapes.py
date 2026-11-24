"""Four shapes that decide a large collision sweep's guards, spill slots and float temporaries under KMC GCC 2.7.2.

Measured with the exact judge on a 1337-instruction N64 collision sweep (`-G0 -mips3 -mgp32 -mfp32 -O2`), each from the
state before it, after `walk_reentry_repairs`:

- `scalar_read_before_copy`: a float read of a vector (`y = v[1];`) that m2c placed after two struct copies out of that
  vector, moved above them (1048 -> 833). cse still holds the value it loaded for the bounds test before the copies;
  a copy through a pointer local is a store cse cannot see past, so after it the value is loaded again and the saved
  register is filled from the stack (`lwc1 $f24, 0x7c($sp)` where the target has `mov.s $f24, $f8`).
- `guard_flag_share`, offered alone and with `u16_counter_above_guard` on every guarded counter (833 -> 560 as one
  child; the flag alone 828, the counters alone 980): a word counter zeroed
  inside its loop's guard moved above it and typed `u16` (the guard's delay slot is then filled from above, as in
  `guard_counter_init_hoist`), and a later section's inline `(p->flags & 4) != 0` / `(p->flags & 4) < n` tests written
  through the flag local the first section already has. The flag's last use then comes after the pointer local that is
  also known zero on that path, so cse's `make_regs_eqv` heads their class with the flag, and the guard compares the
  flag (`sltu $v0, $v1, $v0`) instead of the pointer, whose extra reference had lifted it a saved register too high.
- `u16_counter_above_guard` on a counter already zeroed above a guard on a flag (in that child: 708 -> 560): typed `u16` it is
  an HImode pseudo, never in the flag's class, so combine does not fold the guard and leave a `(use)` of a dead compare
  result that took an 8-byte stack slot.
- `float_temp_merge`: m2c's float temporaries named for one register (`temp_fa0`, `temp_fa0_3`) and a step written
  back into its operand (`d = r - d; ... d * x`) at the sites that compute the same push-out, written as one variable
  (560 -> 475). One pseudo across the four sites is global, and global.c gives it the first free register after the
  blocks' own temporaries: `$f12`, as the target has it.

Candidate rewrites; the exact judge decides each.
"""
import re

from .integer_repair_support import IDENT, edit, view

READ_FIRST = 'scalar_read_before_copy'
FLAG_SHARE = 'guard_flag_share'
COUNTER = 'u16_counter_above_guard'
FLOAT_MERGE = 'float_temp_merge'
FAMILIES = (READ_FIRST, FLAG_SHARE, COUNTER, FLOAT_MERGE)
LIMIT = 6
_DECL = re.compile(rf'(?m)^[ \t]*(?:register\s+)?(?P<type>(?:unsigned\s+|signed\s+)?(?:[su](?:8|16|32)|int|short|char|f32|float)\s*\**)\s*(?P<name>{IDENT})\s*;[ \t]*\n')


def _decls(part):
    return {m['name']: m for m in _DECL.finditer(part.clean, part.opening, part.end)}


def _read_first(source, part):
    out = []
    clean = part.clean
    copy = r'\*\(\([^;]*\*\) ({0})\) = \*\(\([^;]*\*\) ({0})\);'.format(r'[^;()]+')
    for read in re.finditer(rf'(?m)^([ \t]*)({IDENT}) = ([A-Za-z_][\w.]*)\[(\d+)\];[ \t]*\n', clean[:part.end]):
        if read.start() < part.opening:
            continue
        vector = read[3]
        above = clean[max(part.opening, read.start() - 600):read.start()]
        copies = list(re.finditer(rf'(?m)^[ \t]*{copy}[ \t]*\n', above))
        if not copies or not any(vector in c[0] for c in copies):
            continue
        first = read.start() - len(above) + copies[0].start()
        between = clean[first:read.start()]
        if re.search(rf'(?<![\w.]){re.escape(vector)}\s*(?:\[[^]]*\])?\s*=[^=]', between):
            continue
        line = source[read.start():read.end()]
        out.append((READ_FIRST, edit(source, [(read.start(), read.end(), ''), (first, first, line)])))
        if len(out) >= LIMIT:
            break
    return out


def _counters(source, part, decls):
    """(edits, names) for word counters zeroed inside or above a guard `if (X < N)` that compares something else."""
    clean = part.clean
    edits, names = [], []
    inside = re.compile(rf'(?m)^([ \t]*)if \(({IDENT}) < ([^;{{}}]*)\)\s*{{\s*\n[ \t]*({IDENT}) = 0;[ \t]*\n')
    for hit in inside.finditer(clean, part.opening, part.end):
        counter = hit[4]
        if counter == hit[2] or counter not in decls or decls[counter]['type'].strip() not in ('s32', 'int', 'u16'):
            continue
        zero = re.search(rf'(?m)^[ \t]*{counter} = 0;[ \t]*\n', clean[hit.start():hit.end()])
        at = hit.start() + zero.start()
        edits.append((at, hit.start() + zero.end(), ''))
        edits.append((hit.start(), hit.start(), f'{hit[1]}{counter} = 0;\n'))
        names.append(counter)
    above = re.compile(rf'(?m)^[ \t]*{{?\s*({IDENT}) = 0;\s*}}?\s*\n[ \t]*if \(({IDENT}) < ')
    for hit in above.finditer(clean, part.opening, part.end):
        counter = hit[1]
        if counter != hit[2] and counter in decls and decls[counter]['type'].strip() in ('s32', 'int'):
            names.append(counter)
    for counter in dict.fromkeys(names):
        decl = decls[counter]
        if decl['type'].strip() != 'u16':
            edits.append((decl.start('type'), decl.start('type') + len(decl['type'].rstrip()), 'u16'))
    return edits, list(dict.fromkeys(names))


def _counter(source, part):
    decls = _decls(part)
    edits, names = _counters(source, part, decls)
    return [(COUNTER, edit(source, edits))] if edits else []


def _flag_share(source, part):
    out = []
    clean = part.clean
    flags = re.finditer(rf'\b({IDENT}) = (?:{IDENT}|[^;]*->v) & (\d+);', clean[part.opening:part.end])
    for flag in flags:
        name, mask = flag[1], flag[2]
        start = part.opening + flag.end()
        tests = list(re.finditer(rf'if \(\((\([^;{{}}]*\)->v) & {mask}\) (!= 0|< )', clean[start:part.end]))
        if not tests or not any(t[2] == '!= 0' for t in tests):
            continue
        first = next(t for t in tests if t[2] == '!= 0')
        expr = first[1]
        same = [t for t in tests if t[1] == expr]
        at = start + first.start()
        indent = re.search(r'[ \t]*$', source[:at])[0]
        edits = [(at, at, f'{name} = {source[start + first.start(1):start + first.end(1)]} & {mask};\n{indent}')]
        for t in same:
            edits.append((start + t.start(), start + t.end(), f'if ({name} {t[2]}'))
        child = edit(source, edits)
        out.append((FLAG_SHARE, child))
        later = view(child, _name(source, part))
        if later:
            cedits, _ = _counters(child, later, _decls(later))
            if cedits:
                out.append((FLAG_SHARE, edit(child, cedits)))
        if len(out) >= LIMIT:
            break
    return out


def _name(source, part):
    return re.findall(rf'({IDENT})\s*\(', source[:part.opening])[-1]


def _float_merge(source, part):
    clean = part.clean
    decls = _decls(part)
    groups = {}
    for name in decls:
        reg = re.fullmatch(r'temp_(f[a-z]+\d+)(?:_\d+)?', name)
        if reg and decls[name]['type'].strip() in ('f32', 'float'):
            groups.setdefault(reg[1], []).append(name)
    out = []
    for reg, names in sorted(groups.items()):
        if len(names) < 2:
            continue
        survivor = min(names, key=len)
        edits = []
        for name in names:
            if name == survivor:
                continue
            decl = decls[name]
            edits.append((decl.start(), decl.end(), ''))
            for use in re.finditer(rf'(?<![\w.>]){name}\b', clean[:part.end]):
                if use.start() > part.opening and not decl.start() <= use.start() < decl.end():
                    edits.append((use.start(), use.end(), survivor))
        sites = re.findall(rf'\b{survivor} = ({IDENT}) - {IDENT};', clean[part.opening:part.end])
        child = edit(source, edits)
        out.append((FLOAT_MERGE, child))
        if sites:
            back = re.compile(rf'(?m)^([ \t]*)({IDENT}) = {re.escape(sites[0])} - \2;\s*\n((?:[ \t]*{IDENT} = \2 \* [^;]*;\s*\n){{1,3}})')
            text = child
            for hit in list(back.finditer(text))[::-1]:
                var = hit[2]
                body = re.sub(rf'= {var} \*', f'= {survivor} *', hit[3])
                text = text[:hit.start()] + f'{hit[1]}{survivor} = {sites[0]} - {var};\n' + body + text[hit.end():]
            if text != child:
                out.append((FLOAT_MERGE, text))
        if len(out) >= LIMIT:
            break
    return out


_STEPS = (_read_first, _flag_share, _counter, _float_merge)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for step in _STEPS:
        try:
            out.extend(step(source, part))
        except (KeyError, IndexError, StopIteration):
            continue
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
