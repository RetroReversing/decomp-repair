"""A saved best rebuilt as the C a person would restart from: m2c's gotos structured, the search's scaffolding gone.

A function's saved best is often m2c output a long search then dressed in scaffolding: `loop_N:` labels with a
conditional `goto` back, `if (c) goto block_N;` skips, identity `inline_fn*` helpers, `((__repair_field_N *) p)->value`
views of one offset, `__repair_phase_` copies of a local, `do { } while (0)` fences and m2c's `*((T *) (((char *) p) +
N))` derefs. Across ~65 matches of an N64 game agents nearly always threw that best away and wrote a clean rewrite,
then the families did the last steps; started from the saved best, greedy chains stalled at 200-1500. `scaffold_strip`
alone (it declines any `goto`) strips without rebuilding structure and usually scores worse than the best.

`levels` writes the function in cumulative steps, each a faithful rewrite of the one before it (pure source to source;
nothing is compiled or judged here):
  * `clean_rewrite_structure`: m2c's gotos as the statements they stand for. A label whose only `goto` is a
    conditional jump back at the end of the same block is a `do { } while`; an `if (c) goto L;` whose label ends the
    same block's run of statements is `if (!c) { }`; a `goto` to the label right after its innermost loop or switch
    is `break`; a `goto` to a label that only returns is that `return`; `if (c) { do { S } while (c); }` is
    `while (c) { S }`; a `goto` to the next statement and labels nothing jumps to go. gcc builds the same graph from
    either spelling more often than not, so this level usually keeps the score;
  * `clean_rewrite_scaffold`: also one-`return` inline helpers written as their expression (declined when a
    parameter is narrow or floating, or an argument with side effects would be read twice), a `__repair_` local set
    once to a literal written as the literal, `__repair_phase_` names shortened, m2c's deref spelling
    `*((T *) (((char *) p) + N))` written `*(T *)((char *)p + N)`;
  * `clean_rewrite`: also `((__repair_field_N *) p)->value` views written as the deref they name (a struct member and
    a plain deref are different alias sets: 180 -> 595 on one function, so this is the last level), fences opened,
    identical arms collapsed and `scaffold_strip.strip`.
Every rule declines what it cannot prove: a `break` or `continue` the new loop would capture, a declaration the new
block would scope, a label used twice or entered from outside the block, an `else` arm. `variants` offers the levels
that differ; the exact judge decides which is the better start. The match-function skill's `plain_best.py` writes them
beside the saved best when a function is claimed. Measured in decompdecomp's
docs/learnings/experiment/clean-rewrite-start.md."""
import re

from . import identical_arm_collapse_repairs, scaffold_strip
from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'clean_rewrite'
STRUCTURE = 'clean_rewrite_structure'
SCAFFOLD = 'clean_rewrite_scaffold'
FAMILIES = (STRUCTURE, SCAFFOLD, FAMILY)
ROUNDS = 64
IDENT = r'[A-Za-z_]\w*'
TYPES = (r'(?:const\s+|volatile\s+|register\s+|static\s+|unsigned\s+|signed\s+)*(?:[su](?:8|16|32|64)|f32|f64|int|'
         r'char|short|long|float|double|void|struct\s+\w+|union\s+\w+)\b')
DECLARATION = re.compile(rf'(?m)^[ \t]*{TYPES}[\s*]*{IDENT}\s*[=;\[,]')
NARROW = re.compile(r'\b(?:[su](?:8|16)|char|short|f32|f64|float|double)\b')


def _body(source, name):
    """(clean, opening brace, closing brace) of the function `name`, or None."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*\{', clean[span[0]:span[1]])
    if not head:
        return None
    opening = span[0] + head.end() - 1
    end = close(clean, opening, '{', '}')
    return (clean, opening, end - 1) if end else None


def _balanced(clean, start, end):
    """True when clean[start:end] neither closes a brace it did not open nor leaves one open."""
    depth = 0
    for char in clean[start:end]:
        if char in '{(':
            depth += 1
        elif char in '})':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _loose_exit(clean, start, end):
    """True when a `break`/`continue` in clean[start:end] is not inside a loop or switch of its own there."""
    for hit in re.finditer(r'\b(?:break|continue)\b', clean[start:end]):
        position = start + hit.start()
        owned = False
        for loop in re.finditer(r'\b(?:for|while|do|switch)\b', clean[start:position]):
            at = start + loop.start()
            brace = clean.find('{', at, position)
            if brace < 0:
                continue
            stop = close(clean, brace, '{', '}')
            if stop and stop > position:
                owned = True
                break
        if not owned:
            return True
    return False


def _goto_count(clean, label):
    return len(re.findall(r'\bgoto\s+' + re.escape(label) + r'\s*;', clean))


def _cond_goto(clean, at, label=None):
    """(end, condition span) of `if (C) goto L;` or `if (C) { goto L; }` starting at `at`, with L."""
    head = re.compile(r'if\s*\(').match(clean, at)
    if not head:
        return None
    paren = head.end() - 1
    stop = close(clean, paren, '(', ')')
    if not stop:
        return None
    jump = re.compile(r'\s*(\{\s*)?goto\s+(' + IDENT + r')\s*;').match(clean, stop)
    if not jump or (label and jump[2] != label):
        return None
    end = jump.end()
    if jump[1]:
        brace = re.compile(r'\s*\}').match(clean, end)
        if not brace:
            return None
        end = brace.end()
    return end, (paren + 1, stop - 1), jump[2]


def _statement_start(clean, at):
    """True when the statement at `at` stands on its own: not an `else` arm or the body of an unbraced `if`."""
    before = clean[:at].rstrip()
    return not before or before[-1] in ';{}' or (before[-1] == ':' and not before.endswith('::'))


def _indent(text, at):
    line = text.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', text[line:])[0]


def _not(condition):
    condition = condition.strip()
    flipped = negate(condition)
    if flipped:
        return flipped
    inner = re.fullmatch(r'!\s*\((.*)\)', condition, re.S)
    if inner and _balanced(inner[1], 0, len(inner[1])):
        return inner[1].strip()
    return f'!({condition})'


def _entered(clean, start, stop):
    """True when clean[start:stop] holds a `case`/`default` label or a label some `goto` outside it jumps to."""
    if re.search(r'\b(?:case\b[^;:]*|default\s*):', clean[start:stop]):
        return True
    for label in re.finditer(r'(?<![\w.>?:])(' + IDENT + r')\s*:(?!:)', clean[start:stop]):
        jumps = [m.start() for m in re.finditer(r'\bgoto\s+' + re.escape(label[1]) + r'\s*;', clean)]
        if any(not (start <= j < stop) for j in jumps):
            return True
    return False


def _back_loop(source, clean, opening, end):
    """`L: S if (C) goto L;` in one block, L used once, as `do { S } while (C);`."""
    for label in re.finditer(r'(?<![\w.>?:])(' + IDENT + r')\s*:(?!:)', clean[:end]):
        if label.start() <= opening or label[1] in ('default', 'case') or _goto_count(clean, label[1]) != 1:
            continue
        before = clean[:label.start()].rstrip()
        if before and before[-1] not in ';{}':
            continue  # a `?:` or a `case X:`, not a label
        body = label.end()
        for jump in re.finditer(r'\bif\s*\(', clean[body:end]):
            at = body + jump.start()
            found = _cond_goto(clean, at, label[1])
            if not found:
                continue
            stop, (c0, c1), _ = found
            if (not _statement_start(clean, at) or not _balanced(clean, body, at) or _loose_exit(clean, body, at)
                    or DECLARATION.search(clean[body:at]) or _entered(clean, body, at)):
                break
            if not clean[body:at].strip():
                break
            inner = source[body:at].strip('\n').rstrip()
            indent = re.match(r'[ \t]*', inner)[0] if '\n' in inner else _indent(source, at)
            line = source.rfind('\n', 0, label.start()) + 1
            head = line if not source[line:label.start()].strip() else label.start()
            text = (source[:head] + (indent if head == line else '') + 'do\n' + indent + '{\n' + _shift(inner, '  ') + '\n' + indent
                    + '} while (' + source[c0:c1].strip() + ');' + source[stop:])
            return text
    return None


def _shift(text, by):
    return '\n'.join((by + line) if line.strip() else line for line in text.split('\n'))


def _forward_skip(source, clean, opening, end):
    """`if (C) goto L; S L:` in one block, L used once, as `if (!C) { S }`."""
    for jump in re.finditer(r'\bif\s*\(', clean[opening:end]):
        at = opening + jump.start()
        found = _cond_goto(clean, at)
        if not found:
            continue
        stop, (c0, c1), label = found
        if _goto_count(clean, label) != 1 or not _statement_start(clean, at):
            continue
        target = re.compile(r'(?<![\w.>?:])' + re.escape(label) + r'\s*:(?!:)').search(clean, stop, end)
        if (not target or not _balanced(clean, stop, target.start()) or DECLARATION.search(clean[stop:target.start()])
                or _entered(clean, stop, target.start())):
            continue
        if not clean[stop:target.start()].strip():
            text = source[:at] + source[target.end():]
        else:
            indent = _indent(source, at)
            inner = source[stop:target.start()].strip('\n').rstrip()
            text = (source[:at] + 'if (' + _not(source[c0:c1]) + ')\n' + indent + '{\n' + _shift(inner.lstrip(' \t')
                    if '\n' not in inner else inner, '  ') + '\n' + indent + '}\n' + indent + source[target.end():].lstrip(' \t'))
        return text
    return None


def _guarded_do(source, clean, opening, end):
    """`if (C) { do { S } while (C); }` as `while (C) { S }`, C free of side effects."""
    for hit in re.finditer(r'\bif\s*\(', clean[opening:end]):
        at = opening + hit.start()
        paren = clean.index('(', at)
        stop = close(clean, paren, '(', ')')
        condition = re.sub(r'\s+', '', clean[paren + 1:stop - 1])
        if re.search(r'\+\+|--|[^=!<>]=[^=]|\w\s*\(', clean[paren + 1:stop - 1]):
            continue
        shape = re.compile(r'\s*\{\s*do\s*\{').match(clean, stop)
        if not shape:
            continue
        outer = clean.index('{', stop)
        inner = shape.end() - 1
        inner_end = close(clean, inner, '{', '}')
        tail = re.compile(r'\s*while\s*\((.*?)\)\s*;\s*\}', re.S).match(clean, inner_end)
        if not tail or re.sub(r'\s+', '', tail[1]) != condition or close(clean, outer, '{', '}') != tail.end():
            continue
        if not _balanced(clean, inner_end, tail.end() - 1) or 'else' in clean[tail.end():tail.end() + 6].split():
            continue
        if re.match(r'\s*else\b', clean[tail.end():]):
            continue
        indent = _indent(source, at)
        body = source[inner + 1:inner_end - 1].strip('\n')
        return (source[:at] + 'while (' + source[paren + 1:stop - 1].strip() + ')\n' + indent + '{\n' + body + '\n'
                + indent + '}' + source[tail.end():])
    return None


def _dead_labels(source, clean, opening, end):
    """A `goto L;` straight before `L:` and labels nothing jumps to, removed."""
    hit = re.compile(r'\bgoto\s+(' + IDENT + r')\s*;\s*\1\s*:(?!:)').search(clean, opening, end)
    if hit and _statement_start(clean, hit.start()):
        return source[:hit.start()] + source[hit.end():] if _goto_count(clean, hit[1]) == 1 else None
    for label in re.finditer(r'(?m)^[ \t]*(' + IDENT + r')\s*:(?!:)[ \t]*\n?', clean[:end]):
        if label.start() <= opening or label[1] in ('default', 'case') or re.search(r'\bgoto\s+' + label[1] + r'\b', clean):
            continue
        after = clean[label.end():].lstrip()
        if after.startswith('}'):
            continue  # a label ending a block needs a statement: leave it
        return source[:label.start()] + source[label.end():]
    return None


def _constructs(clean, opening, end):
    """[(keyword start, body brace, extent end)] of every braced loop and switch in the function: the extent of a
    `do` ends after its `while (...);`."""
    out = []
    for hit in re.finditer(r'\b(for|while|do|switch)\b', clean[opening:end]):
        at = opening + hit.start()
        word = hit[1]
        if word == 'do':
            brace = re.compile(r'do\s*\{').match(clean, at)
            if not brace:
                continue
            brace = brace.end() - 1
            stop = close(clean, brace, '{', '}')
            tail = re.compile(r'\s*while\s*\(').match(clean, stop or 0)
            if not stop or not tail:
                continue
            paren_end = close(clean, tail.end() - 1, '(', ')')
            semi = re.compile(r'\s*;').match(clean, paren_end or 0)
            if not semi:
                continue
            out.append((at, brace, semi.end()))
            continue
        paren = re.compile(word + r'\s*\(').match(clean, at)
        if not paren:
            continue
        stop = close(clean, paren.end() - 1, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, stop or 0)
        if not brace:
            continue  # a do/while tail or an unbraced body
        brace = brace.end() - 1
        body_end = close(clean, brace, '{', '}')
        if body_end:
            out.append((at, brace, body_end))
    return out


def _innermost(constructs, position):
    inside = [c for c in constructs if c[1] < position < c[2]]
    return max(inside, key=lambda c: c[1]) if inside else None


def _unbraced_loop(clean, start, stop):
    """True when a `for`/`while` between start and stop has an unbraced body (a `break` there would be its own)."""
    for loop in re.finditer(r'\b(?:for|while)\s*\(', clean[start:stop]):
        end = close(clean, start + loop.end() - 1, '(', ')')
        if end and not re.compile(r'\s*[{;]').match(clean, end):
            return True
    return False


def _jump_exits(source, clean, opening, end):
    """A `goto L;` whose label stands right after the innermost loop or switch around it, written `break;`; a `goto L;`
    whose label introduces a lone `return X;` written as that return (m2c's shared exits)."""
    constructs = _constructs(clean, opening, end)
    for jump in re.finditer(r'\bgoto\s+(' + IDENT + r')\s*;', clean[opening:end]):
        at = opening + jump.start()
        label = jump[1]
        owner = _innermost(constructs, at)
        if owner and not _unbraced_loop(clean, owner[1], at):
            after = re.compile(r'\s*' + re.escape(label) + r'\s*:(?!:)').match(clean, owner[2])
            if after:
                return source[:at] + 'break;' + source[at + len(jump[0]):]
        target = re.compile(r'(?<![\w.>?:])' + re.escape(label) + r'\s*:(?!:)\s*return\b([^;{}]*);').search(clean, opening, end)
        if target and not re.search(r'\+\+|--|[^=!<>]=[^=]|\w\s*\(', target[1]):
            value = source[target.start(1):target.end(1)].strip()
            return source[:at] + ('return ' + value + ';' if value else 'return;') + source[at + len(jump[0]):]
    return None


def structure(source, name):
    """The function with its gotos structured, its fences opened and identical arms collapsed, or None."""
    text = source
    for _ in range(ROUNDS):
        part = _body(text, name)
        if not part:
            break
        clean, opening, end = part
        for rule in (_dead_labels, _jump_exits, _back_loop, _forward_skip, _guarded_do):
            new = rule(text, clean, opening, end)
            if new and new != text:
                text = new
                break
        else:
            break
    return text if text != source else None


def plain(source, name, header=''):
    """Fences opened, identical arms collapsed and `scaffold_strip.strip`: what a search kept only for its score."""
    text = _field_views(source, name) or source
    text = scaffold_strip.unfence(text, name) or text
    for _ in range(6):
        arms = identical_arm_collapse_repairs.variants(text, name)
        if not arms:
            break
        text = arms[0][1]
    try:
        text = scaffold_strip.strip(text, name, header) or text
    except Exception:  # a strip that cannot read the function leaves it as it is
        pass
    return text if text != source else None


# ---------------------------------------------------------------- scaffolding

HELPER = re.compile(r'(?:(?:inline|static|__inline__|__inline)\s+)+(?P<ret>[\w\s*]+?)\s*\b(?P<name>' + IDENT
                    + r')\s*\((?P<params>[^()]*)\)\s*\{\s*return\b(?P<expr>[^;{}]*);\s*\}[ \t]*\n?')
PURE = re.compile(r'\s*(?:' + IDENT + r'|0[xX][0-9a-fA-F]+|\d+[uUlL]*|&\s*' + IDENT + r')\s*$')


def _split_args(text):
    out, depth, last = [], 0, 0
    for i, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == ',' and depth == 0:
            out.append(text[last:i])
            last = i
            last += 1
    out.append(text[last:])
    return [arg.strip() for arg in out] if text.strip() else []


def _inline_helpers(source, name):
    """Calls of one-`return` inline helpers written as the expression, helpers nothing calls removed."""
    text = source
    for helper in reversed(list(HELPER.finditer(_blank(source)))):
        if helper['name'] == name:
            continue
        ret = helper['ret'].strip()
        params = [] if helper['params'].strip() in ('', 'void') else [p.strip() for p in helper['params'].split(',')]
        names = []
        for param in params:
            m = re.fullmatch(r'([\w\s*]+?)\s*\b(' + IDENT + r')', param)
            if not m or ('*' not in m[1] and NARROW.search(m[1])):
                names = None
                break
            names.append(m[2])
        if names is None or ('*' not in ret and re.search(r'\b(?:float|double|f32|f64)\b', ret)):
            continue
        expr = helper['expr'].strip()
        uses = {p: len(re.findall(r'\b' + p + r'\b', expr)) for p in names}
        if len([d for d in HELPER.finditer(_blank(text)) if d['name'] == helper['name']]) != 1:
            continue
        call = re.compile(r'\b' + re.escape(helper['name']) + r'\s*\(')
        bad = False
        for _ in range(ROUNDS):  # innermost calls first: an argument may call the helper again
            tclean = _blank(text)
            definition = [d for d in HELPER.finditer(tclean) if d['name'] == helper['name']][0].span()
            edits = []
            for m in call.finditer(tclean):
                if definition[0] <= m.start() < definition[1]:
                    continue
                if m.start() < definition[0]:
                    bad = True
                    break
                stop = close(tclean, m.end() - 1, '(', ')')
                if not stop:
                    bad = True
                    break
                if call.search(tclean, m.end(), stop) or (edits and m.start() < edits[-1][1]):
                    continue
                args = _split_args(text[m.end():stop - 1])
                if len(args) != len(names) or any(uses[p] > 1 and not PURE.match(a) for p, a in zip(names, args)):
                    bad = True
                    break
                given = dict(zip(names, args))
                body = re.sub(r'\b(' + '|'.join(map(re.escape, names)) + r')\b', lambda w, given=given: f'({given[w[1]]})',
                              expr) if names else expr
                edits.append((m.start(), stop, f'(({ret}) ({body}))'))
            if bad or not edits:
                break
            for start, stop, replacement in reversed(edits):
                text = text[:start] + replacement + text[stop:]
        tclean = _blank(text)
        definition = [d for d in HELPER.finditer(tclean) if d['name'] == helper['name']][0].span()
        if bad or any(not (definition[0] <= m.start() < definition[1]) for m in call.finditer(tclean)):
            continue
        text = text[:definition[0]] + text[definition[1]:]
    return text if text != source else None


FIELD = re.compile(r'typedef\s+struct\s*\{\s*(?:unsigned\s+char\s+pad\s*\[\s*(?P<pad>\d+)\s*\]\s*;\s*)?(?P<type>[\w\s*]+?)'
                   r'\s*\bvalue\s*;\s*\}\s*(?P<name>__repair_field_\d+)\s*;[ \t]*\n?')


def _field_views(source, name):
    """`((__repair_field_N *) p)->value` written as the deref it is, the typedefs nothing names removed."""
    clean = _blank(source)
    fields = {m['name']: (int(m['pad'] or 0), m['type'].strip()) for m in FIELD.finditer(clean)}
    text = source
    for field, (pad, kind) in fields.items():
        for _ in range(ROUNDS):
            tclean = _blank(text)
            hit = re.compile(r'\(\(\s*' + field + r'\s*\*\s*\)').search(tclean)
            if not hit:
                break
            stop = close(tclean, hit.start(), '(', ')')
            arrow = re.compile(r'\s*->\s*value\b').match(tclean, stop)
            if not arrow:
                break
            pointer = text[hit.end():stop - 1].strip()
            base = f'(char *) ({pointer})' if not re.fullmatch(IDENT, pointer) else f'(char *) {pointer}'
            spelled = f'(*(({kind} *) ({base} + {pad})))' if pad else f'(*(({kind} *) ({pointer})))'
            text = text[:hit.start()] + spelled + text[arrow.end():]
        tclean = _blank(text)
        if len(re.findall(r'\b' + field + r'\b', tclean)) == 1:
            typedef = re.compile(r'typedef\s+struct\s*\{[^{}]*\}\s*' + field + r'\s*;[ \t]*\n?').search(tclean)
            if typedef:
                text = text[:typedef.start()] + text[typedef.end():]
    return text if text != source else None


def _phase_names(source, name):
    """`__repair_phase_x` (and `__repair_phase___repair_phase_x`) renamed to a plain unused name."""
    part = _body(source, name)
    if not part:
        return None
    clean = _blank(source)
    names = sorted(set(re.findall(r'\b((?:__repair_phase_)+)(' + IDENT + r')\b', clean)), key=lambda m: -len(m[0]))
    text = source
    for prefix, base in names:
        old = prefix + base
        if base.startswith('_') or not re.search(r'\b' + re.escape(old) + r'\b', text):
            continue
        taken = set(re.findall(IDENT, _blank(text)))
        index = 2
        new = f'{base}_p'
        while new in taken:
            new = f'{base}_p{index}'
            index += 1
        text = re.sub(r'\b' + re.escape(old) + r'\b', new, text)
    return text if text != source else None


LITERAL = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'


def _literal_locals(source, name):
    """A `__repair_` local set once to a literal, read only after that and never through its address, written as the
    literal (the search's way of keeping a constant in a register: `__repair_literal = 0; if (n > __repair_literal)`)."""
    part = _body(source, name)
    if not part:
        return None
    clean, opening, end = part
    for decl in re.finditer(r'(?m)^[ \t]*(?:register\s+)?(?:[su](?:8|16|32)|int|unsigned\s+int|short|long|char)\s+'
                            r'(__repair_\w+)\s*;[ \t]*\n', clean[:end]):
        if decl.start() < opening:
            continue
        local = decl[1]
        sets = list(re.finditer(r'\b' + local + r'\s*=(?!=)\s*(' + LITERAL + r')\s*;[ \t]*\n?', clean))
        everything = list(re.finditer(r'\b' + local + r'\b', clean))
        if len(sets) != 1 or re.search(r'&\s*' + local + r'\b|\b' + local + r'\s*(?:\+\+|--|[-+*/|&^<>]=)|(?:\+\+|--)\s*'
                                       + local + r'\b', clean):
            continue
        assign = sets[0]
        reads = [m for m in everything if m.start() not in (decl.start(1), assign.start())]
        if any(m.start() < assign.start() for m in reads):
            continue
        value = assign[1]
        text = source
        for m in sorted(reads + [assign], key=lambda m: -m.start()):
            text = text[:m.start()] + (value if m in reads else '') + text[m.end():]
        text = text[:decl.start()] + text[decl.end():]
        return text
    return None


def scaffold(source, name, header=''):
    text = source
    for _ in range(8):
        text = _literal_locals(text, name) or text
    for rule in (_inline_helpers, _phase_names, spelling):
        text = rule(text, name) or text
    return text if text != source else None


# ---------------------------------------------------------------- spelling

DEREF = re.compile(r'\*\(\((?P<type>[\w\s]+?\s*\*+)\s*\)\s*\(\(\(char\s*\*\)\s*(?P<base>' + IDENT
                   + r')\)\s*\+\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\)\)')
DEREF0 = re.compile(r'\*\(\((?P<type>[\w\s]+?\s*\*+)\s*\)\s*\(\(char\s*\*\)\s*(?P<base>' + IDENT + r')\)\)')
PLUS0 = re.compile(r'\(\(\(char\s*\*\)\s*(?P<base>' + IDENT + r')\)\s*\+\s*0\)')


def spelling(source, name):
    """m2c's deref spelling written the short way, offsets of zero dropped."""
    part = _body(source, name)
    if not part:
        return None
    _, opening, end = part
    body = source[opening:end]
    for _ in range(ROUNDS):
        new = DEREF.sub(lambda m: f'*({m["type"].strip()})((char *){m["base"]} + {m["off"]})'
                        if m['off'] not in ('0', '0x0') else f'*({m["type"].strip()}){m["base"]}', body)
        new = DEREF0.sub(lambda m: f'*({m["type"].strip()}){m["base"]}', new)
        new = PLUS0.sub(lambda m: f'((char *){m["base"]})', new)
        if new == body:
            break
        body = new
    text = source[:opening] + body + source[end:]
    return text if text != source else None


def levels(source, name, header=''):
    """[(family, source)]: each cumulative level that changed the function, the fullest last, without repeats."""
    out, seen = [], {source}
    text = source
    for family, step in ((STRUCTURE, lambda t: structure(t, name)), (SCAFFOLD, lambda t: scaffold(t, name, header)),
                         (FAMILY, lambda t: plain(t, name, header))):
        try:
            text = step(text) or text
        except Exception:  # one rule's bug must not take the other levels with it
            continue
        if text not in seen:
            seen.add(text)
            out.append((family, text))
    return out


def clean(source, name, header=''):
    """The fullest clean rewrite, or None when nothing changed."""
    found = levels(source, name, header)
    return found[-1][1] if found else None


def _single_steps(source, name, header):
    """What one older family offers for `source` alone: a level equal to one of these is that family's child."""
    out = {text for _, text in identical_arm_collapse_repairs.variants(source, name)}
    for step in (lambda: scaffold_strip.unfence(source, name), lambda: scaffold_strip.strip(source, name, header),
                 lambda: scaffold_strip.plain(source, name, header)):
        try:
            out.add(step())
        except Exception:  # a family that cannot read the function offers nothing
            pass
    return out


def variants(source, name, header=''):
    """The levels, without one that a single older family already offers (the caller keeps the first family that
    offers a source, and the child keeps that family's name: an arm collapse stays `identical_arm_collapse`)."""
    found = levels(source, name, header)
    if not found:
        return []
    taken = _single_steps(source, name, header)
    return [(family, text) for family, text in found if text not in taken]


# last: a level often equals one family's single child (an arm collapse, a fence opened), and the caller keeps the
# first family that offers a source, so the specific families keep their names


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 5000}
