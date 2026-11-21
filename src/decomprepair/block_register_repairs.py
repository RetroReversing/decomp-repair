"""Three source shapes that decide which registers a function's loops get, found by hand on an N64 function.

KMC GCC 2.7.2 (-O2) allocates a pseudo that lives in several blocks globally, but a value used in one block only
by the local pass, so how a draft names and scopes its variables decides which values sit in saved registers. An
836-byte-class function with four loops and 38 register-only differences went from 1175 to 280 with these:

- `symbol_pointer_inline`: `s16 *p; ... p = &G; memset(p, ...); p[i]` becomes `(&G)[i]` with no local. The draft's
  pointer is a pseudo of its own; the game's code had only the global's address, which gcc keeps in the register
  the call arguments already used and copies to a new one at the loop (`move $s2, $s0`). 750 -> 470, and the
  whole first loop matched.
- `block_temp_split`: a function-wide temporary that each loop sets before reading (the slot index, a text
  buffer) becomes one variable per loop. A name shared by loops is one pseudo for the allocator, so one saved
  register for all of them. 470 -> 280.
- `do_while_to_for`: `i = 0; do { ...; i++; } while (c);` becomes `for (i = 0; c; i++) { ... }`, which gcc tests
  at the loop head with no copy of the test before the loop. 1130 -> 770 (with the loop's pointer declared outside).
  The init is also offered left where it was, as `for (; c; i++)`: gcc emits a header init right before the loop,
  after the pointer declarations in front of it. 80 -> 20.

- `inline_nonzero_test`: `if (v != 0)` becomes `if (repair_nonzero(v))` with `static inline int repair_nonzero(int v)
  { return v != 0; }` above the function. After a plain `beqz v` gcc's CSE knows `v == 0` on the else path and
  replaces `v` there by any register holding zero (`slt $v0, $s4, $v0`); through the helper it keeps `v`'s own
  register, as the game's code did. 20 -> 0 on the N64 function (found by the deep permuter's inline rewrite).

Each rewrite only renames, inlines or re-spells: what is computed does not change (the for-loop form assumes the
condition holds on entry, which the judge settles). Proposals only; the compiler and the byte judge decide.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

SYMBOL = 'symbol_pointer_inline'
SPLIT = 'block_temp_split'
FOR = 'do_while_to_for'
NONZERO = 'inline_nonzero_test'
FAMILIES = (SYMBOL, SPLIT, FOR, NONZERO)

IDENT = r'[A-Za-z_]\w*'
LIMIT = 4
SPLIT_LIMIT = 16  # a function with four loops has a few temporaries that cross them


def variants(source, name):
    result = []
    for family, generator in ((SYMBOL, _symbol_pointers), (SPLIT, _split_temporaries), (FOR, _for_loops), (NONZERO, _nonzero_tests)):
        result += [(family, text) for text in generator(source, name)]
    return result


def _body(source, name):
    span = find(source, name)
    clean = _blank(source)
    if not span or re.search(r'\b(?:volatile\s+\w+\s*\*\s*)?(?:asm|__asm__)\b', clean[span[0]:span[1]]):
        return None
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, opening, end) if end else None


def _edit(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def _mentions(clean, name, start, end):
    return [m for m in re.finditer(r'(?<![\w.>])' + re.escape(name) + r'\b', clean[start:end])]


# -- symbol_pointer_inline ---------------------------------------------------------------------------------------

def _symbol_pointers(source, name):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    body = clean[opening:end]
    locals_ = {m['name'] for m in re.finditer(rf'(?m)^[ \t]*(?:[\w]+[ \t]+)+\**[ \t]*(?P<name>{IDENT})[ \t]*(?:=[^;]*)?;', body)}
    found = []
    # `T *p = &G;` and `T *p; ... p = &G;`
    initialised = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?:(?:const|unsigned|signed|struct)\s+)*{IDENT}\s*\*\s*(?P<p>{IDENT})\s*=\s*&\s*(?P<g>{IDENT})\s*;[ \t]*\n')
    declared = re.compile(rf'(?m)^[ \t]*(?:(?:const|unsigned|signed|struct)\s+)*{IDENT}\s*\*\s*(?P<p>{IDENT})\s*;[ \t]*\n')
    assigned = re.compile(rf'(?m)^[ \t]*(?P<p>{IDENT})\s*=(?!=)\s*&\s*(?P<g>{IDENT})\s*;[ \t]*\n')
    for hit in initialised.finditer(body):
        found.append((hit['p'], hit['g'], [(hit.start(), hit.end())]))
    for decl in declared.finditer(body):
        sets = [m for m in assigned.finditer(body) if m['p'] == decl['p']]
        if len(sets) == 1:
            found.append((decl['p'], sets[0]['g'], [(decl.start(), decl.end()), (sets[0].start(), sets[0].end())]))
    chosen = []
    for pointer, symbol, spans in found:
        if symbol in locals_ or pointer == symbol:
            continue
        reads = [m for m in _mentions(clean, pointer, opening, end) if not any(
            opening + a <= opening + m.start() < opening + b for a, b in spans)]
        # `&p[i]` takes an element's address, `&p` the pointer's own
        address = [m for m in reads if clean[opening + m.start() - 1:opening + m.start()] == '&'
                   and not re.match(r'\s*\[', clean[opening + m.end():])]
        if not reads or address or any(re.match(r'\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', clean[opening + m.end():]) for m in reads):
            continue
        # the pointer is only read, and it is not a parameter of a nested declaration of the same name
        chosen.append((pointer, symbol, spans, reads))
    if not chosen:
        return []

    def rewrite(items):
        edits = []
        for pointer, symbol, spans, reads in items:
            edits += [(opening + a, opening + b, '') for a, b in spans]
            edits += [(opening + m.start(), opening + m.end(), f'(&{symbol})') for m in reads]
        return _edit(source, edits)
    result = [rewrite(chosen)] if len(chosen) > 1 else []
    result += [rewrite([item]) for item in chosen]
    return list(dict.fromkeys(result))[:LIMIT]


# -- block_temp_split --------------------------------------------------------------------------------------------

def _loops(clean, opening, end):
    """`(start, end)` of every loop statement, outermost first: do/while, for and while with a braced body."""
    spans = []
    for hit in re.finditer(r'\b(?:do|for|while)\b', clean[opening:end]):
        at = opening + hit.start()
        if hit[0] == 'do':
            brace = clean.find('{', at)
            if not re.fullmatch(r'do\s*', clean[at:brace]):
                continue
            body_end = close(clean, brace, '{', '}')
            tail = re.match(r'\s*while\s*\(', clean[body_end:end]) if body_end else None
            stop = close(clean, body_end + tail.end() - 1) if tail else None
            if stop:
                spans.append((at, stop))
        else:
            paren = clean.find('(', at)
            if paren < 0 or clean[at + len(hit[0]):paren].strip():
                continue
            after = close(clean, paren)
            if after and re.match(r'\s*\{', clean[after:end]):
                brace = clean.find('{', after)
                stop = close(clean, brace, '{', '}')
                if stop:
                    spans.append((at, stop))
    return sorted(set(spans))


def _split_temporaries(source, name):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    loops = _loops(clean, opening, end)
    if len(loops) < 2:
        return []
    top = [s for s in loops if not any(o[0] <= s[0] and s[1] <= o[1] and o != s for o in loops)]
    declaration = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?P<type>(?:(?:const|unsigned|signed|struct)\s+)*{IDENT}(?:\s*\*)*)\s*(?P<v>{IDENT})\s*;[ \t]*\n')
    candidates = []
    for decl in declaration.finditer(clean, opening, end):
        var = decl['v']
        uses = [m for m in _mentions(clean, var, opening, end) if not decl.start() <= opening + m.start() < decl.end()]
        if len(uses) < 3 or re.search(r'(?<![\w.])&\s*' + var + r'\b', clean[opening:end]):
            continue
        groups = {}
        for m in uses:
            at = opening + m.start()
            inside = next((i for i, s in enumerate(top) if s[0] <= at < s[1]), None)
            groups.setdefault(inside, []).append(m)
        if len([g for g in groups if g is not None]) < 2:
            continue
        ok = True
        for group, items in groups.items():
            first = opening + items[0].start()
            # the first mention of each group is a plain set at a statement boundary, never a read
            line = clean.rfind('\n', 0, first) + 1
            if not (re.fullmatch(r'[ \t]*', clean[line:first]) or re.fullmatch(r'[ \t]*(?:\w+\s*=\s*[^;]*;\s*)?', clean[line:first])) \
                    or not re.match(r'\s*=(?!=)', clean[opening + items[0].end():]):
                ok = False
            elif re.search(r'\b' + var + r'\b', clean[first + len(var):first + len(var) + 1]):
                ok = False
        if ok:
            candidates.append((decl, groups))
    result = []
    for decl, groups in candidates:
        var = decl['v']
        names = {}
        for index, group in enumerate(g for g in groups if g is not None):
            names[group] = f'{var}_{chr(ord("b") + index)}'
        spans = {g: [(opening + m.start(), opening + m.end()) for m in items] for g, items in groups.items()}

        def build(selected, decl=decl, names=names, spans=spans):
            edits = []
            for group in selected:
                edits += [(a, b, names[group]) for a, b in spans[group]]
            added = ''.join(f"{decl['ind']}{decl['type']} {names[g]};\n" for g in selected)
            edits.append((decl.end(), decl.end(), added))
            return _edit(source, edits)
        loops_with = [g for g in groups if g is not None]
        # one loop alone first (the loops after the first), then all of them: the judge tells which register
        # the loops disagree about
        result += [build([g]) for g in loops_with[1:]] if len(loops_with) > 2 else []
        result.append(build(loops_with[1:]))
        if None in groups:
            result.append(build(loops_with))
    return list(dict.fromkeys(result))[:SPLIT_LIMIT]


# -- do_while_to_for ---------------------------------------------------------------------------------------------

def _for_loops(source, name):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    result = []
    for hit in re.finditer(r'\bdo\s*\{', clean[opening:end]):
        start = opening + hit.start()
        brace = opening + hit.end() - 1
        body_end = close(clean, brace, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[body_end:end]) if body_end else None
        if not tail:
            continue
        paren = body_end + tail.end() - 1
        stop = close(clean, paren)
        if not stop or not re.match(r'\s*;', clean[stop:end]):
            continue
        condition = source[paren + 1:stop - 1].strip()
        inner = clean[brace + 1:body_end - 1]
        step = re.search(rf'(?:(?P<v>{IDENT})\s*(?:\+\+|\+=\s*1|=\s*(?P=v)\s*\+\s*1)|\+\+\s*(?P<prefix>{IDENT}))\s*;\s*$', inner)
        if step and step['prefix']:
            # Make the prefix spelling available to the same checks as the postfix one.
            var = step['prefix']
        elif step:
            var = step['v']
        else:
            continue
        # A saved search can write the back edge as (i + 1) <= N after i has already
        # advanced. A head test of i < N restores the same iteration count when it
        # starts at zero and the body cannot change or expose i.
        shifted = re.fullmatch(rf'\(\s*{re.escape(var)}\s*\+\s*1\s*\)\s*<=\s*(?P<n>\d+)(?P<suffix>[uU]?)', condition)
        before = clean[opening:start]
        immediate = re.search(rf'(?<![\w.>]){re.escape(var)}\s*=\s*0\s*;\s*$', before)
        body_without_step = inner[:step.start()]
        limit = int(shifted['n']) if shifted else 0
        altered = re.search(rf'(?:\+\+|--|&)\s*{re.escape(var)}\b|\b{re.escape(var)}\s*(?:\+\+|--|[+*/%&|^\-]?=(?!=))', body_without_step)
        local = re.search(rf'\b(?:u32|s32|unsigned\s+int|int)\s+{re.escape(var)}\s*;', clean[opening:start])
        address_taken = re.search(rf'&\s*{re.escape(var)}\b', clean[opening:end])
        if (shifted and immediate and local and not address_taken and 0 < limit <= 127 and not altered
                and not re.search(r'\bcontinue\b', body_without_step)):
            init_start = opening + immediate.start()
            semicolon = stop + clean[stop:end].index(';') + 1
            head = f'for ({var} = 0; {var} < {shifted["n"]}{shifted["suffix"]}; ++{var}) {{'
            result.append(_edit(source, [(init_start, brace + 1, head),
                                         (brace + 1 + step.start(), semicolon, '}')]))
            if len(result) >= LIMIT:
                break
        if shifted or step['prefix']:
            continue
        if not step or re.search(r'\bcontinue\b', inner) or not re.search(r'\b' + step['v'] + r'\b', condition):
            continue
        var = step['v']
        # `var = INIT;` right before the loop, with only declarations and bare blocks between
        before = clean[opening:start]
        init = None
        for m in re.finditer(rf'(?m)^[ \t]*{var}\s*=(?!=)\s*(?P<init>[^;]+);[ \t]*\n', before):
            init = m
        if not init:
            continue
        between = before[init.end():]
        if any(not re.fullmatch(r'\s*(?:\{|(?:volatile\s+|const\s+|unsigned\s+)*\w+\s*\*?\s*\w+(?:\s*=[^;]*)?;)?\s*', line)
               for line in between.split('\n')):
            continue
        init_text = source[opening + init.start('init'):opening + init.end('init')].strip()
        line = clean.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        semicolon = stop + clean[stop:end].index(';') + 1
        edits = [(opening + init.start(), opening + init.end(), ''),
                 (start, brace + 1, f'for ({var} = {init_text}; {condition}; {var}++) {{'),
                 (clean.rfind('\n', brace, brace + 1 + step.start()) if clean[brace:brace + 1 + step.start()].count('\n') else brace + 1 + step.start(),
                  semicolon, f'\n{indent}}}')]
        result.append(_edit(source, edits))
        # The init stays a statement of its own: gcc places a for-header init right before the loop, after the
        # loop's pointer declarations, and the game's code had it before them (80 -> 20 on the N64 function).
        kept = [e for e in edits if e[0] != opening + init.start()]
        kept[0] = (start, brace + 1, f'for (; {condition}; {var}++) {{')
        result.append(_edit(source, kept))
        if len(result) >= LIMIT:
            break
    return result


# -- inline_nonzero_test -----------------------------------------------------------------------------------------

HELPER = 'repair_nonzero'


def _nonzero_tests(source, name):
    part = _body(source, name)
    if not part or re.search(r'\b' + HELPER + r'\b', source):
        return []
    clean, opening, end = part
    tests = [m for m in re.finditer(rf'\bif\s*\(\s*(?P<v>{IDENT})\s*!=\s*0\s*\)', clean[opening:end])]
    if not tests:
        return []
    span = find(source, name)
    line = source.rfind('\n', 0, span[0]) + 1
    helper = f'static inline int {HELPER}(int value) {{ return value != 0; }}\n'

    def build(selected):
        edits = [(opening + m.start(), opening + m.end(), f'if ({HELPER}({m["v"]}))') for m in selected]
        edits.append((line, line, helper))
        return _edit(source, edits)
    # every test of a variable the function sets itself first (the key-mode byte), then all, then each alone
    result = [build(tests)] if len(tests) > 1 else []
    result += [build([m]) for m in tests[:LIMIT + 2]]
    return list(dict.fromkeys(result))
