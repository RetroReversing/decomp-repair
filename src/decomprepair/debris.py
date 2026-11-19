"""Changes the permuter's bugs left in saved C, taken out again.

Two of the random rewrites changed what the C means and were kept because the byte score went up:
- `_toggle_register` declared `register D_80102ED4 = 0;`, a new local where the C stored to a global (0.5.11);
- `_add_cast` cut a pointer to 16 bits inside a pointer cast, `(char *)((unsigned short)D_80109698) + 0xFC`, and cast
  type names, `((unsigned)char *)` (0.5.16), and narrowed hex literals, `(unsigned short)0xDA380003` storing 3 where an
  N64 function stored a display-list command (0.5.16), and `(unsigned short)` on a variable in arithmetic (0.5.19).
Repair families left scaffolding behind as well, which is C nobody wrote either and which keeps the families that
would restore the game's shape from matching: `do { … } while (0)` wrappers and `/*__repair_…*/` markers
(loop_weight_repairs), `__repair_rows:` goto loops (loop_storage_shapes), single-assignment `__repair_literal` locals
(constant_local), single-use `__repair_addr`/`__repair_value`/`__repair_result_*` temporaries, and the
`__repair_phase_storage` union. Each comes out only where the C without it means exactly the same (`_scaffolding`).
Neither is C anyone wrote, and every correct candidate scores worse than C holding them, so a search that starts from
such a best never improves it again. `clean` gives the C without them (or None when there is nothing to take out); the
caller judges it and keeps its real score, as decompdecomp's deep pass does for the `register` case.
"""
import re

INTEGER_CASTS = r'(?:unsigned\s+short|unsigned\s+char|unsigned|short|int|s32|u32|s16|u16|s8|u8|uInt|uLong)'
# an integer cast written onto a pointer cast's operand: `*)((unsigned short)X)` and `*)(unsigned short)X`
POINTER_CUT = re.compile(r'(\*\s*\)\s*\(\s*)\(\s*' + INTEGER_CASTS + r'\s*\)\s*([A-Za-z_]\w*)\s*\)')
# a cast written onto a type name: `((unsigned)char *)`
TYPE_CAST = re.compile(r'\(\s*' + INTEGER_CASTS + r'\s*\)\s*(char|short|int|long|void|float|double|s8|u8|s16|u16|s32|u32|f32)'
                       r'(\s*\*)')
# a 16-bit cast the permuter put on a variable that is an operand of arithmetic: m2c writes s16/u16, never these
# spellings, and `(unsigned short)flags | 1` kept only the low half of a word the game ORed whole (0.5.19)
VARIABLE_CUT = re.compile(r'\(\s*(?:unsigned\s+short|short)\s*\)\s*(?=[A-Za-z_]\w*\s*(?:[|&^+\-*/%]|<<|>>)(?!=))')
# a narrowing cast on a hex literal that doesn't fit the type (nobody writes `(u16)0xDA380003` for 3)
LITERAL_CAST = re.compile(r'\(\s*(unsigned\s+short|unsigned\s+char|short|s16|u16|s8|u8)\s*\)\s*(0[xX][0-9a-fA-F]+)[uU]?\b')
WIDTH = {'unsigned short': 0xFFFF, 'short': 0xFFFF, 's16': 0xFFFF, 'u16': 0xFFFF, 'unsigned char': 0xFF, 's8': 0xFF,
         'u8': 0xFF}
# value_repairs' pointer split, `q = (char *)(b); q += (s32)(K);`: one sum written as two (0.5.16 stopped it adding K
# times the element size; the split left in saved C still keeps gcc from treating `q` as `b`'s field address)
POINTER_SPLIT = re.compile(r'(?P<q>[A-Za-z_]\w*)\s*=\s*\(\s*char\s*\*\s*\)\s*\((?P<b>[^;()]*)\)\s*;\s*'
                           r'(?P=q)\s*\+=\s*\(\s*s32\s*\)\s*\((?P<k>[^;()]*)\)\s*;')
UNTYPED_REGISTER = re.compile(r'(?<![\w.])register\s+(?=[A-Za-z_]\w*\s*=(?!=))')


IDENT = r'[A-Za-z_]\w*'
DECLARATION = re.compile(r'\s*(?:(?:unsigned|signed|const|volatile|struct|union)\s+)*[A-Za-z_]\w*[\s*]+[A-Za-z_]\w*\s*'
                         r'(?:\[[^]]*\])?\s*(?:=[^;]*)?;')


def _close(text, start, left='{', right='}'):
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == left) - (text[i] == right)
        if depth == 0:
            return i + 1
    return None


def _jumps_out(body):
    """A `break` or `continue` in `body` that isn't inside a loop or switch of its own (it would bind elsewhere)."""
    for m in re.finditer(r'\b(break|continue)\b', body):
        nest, opened = body[:m.start()], 0
        for k in re.finditer(r'\b(for|while|do|switch)\b', nest):
            brace = nest.find('{', k.end())
            if brace >= 0 and _close(body, brace) and _close(body, brace) > m.start():
                opened += 1
        if not opened:
            return True
    return False


def _unwrap_do_zero(text):
    """`do { S } while (0);` is `S`, when no `break`/`continue` in S binds to it."""
    for m in reversed(list(re.finditer(r'\bdo\s*\{', text))):
        brace = text.index('{', m.start())
        end = _close(text, brace)
        tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', text[end:]) if end else None
        if not tail:
            continue
        body = text[brace + 1:end - 1]
        if _jumps_out(body):
            continue
        inner = body.strip()
        keep = DECLARATION.match(inner) is not None
        text = text[:m.start()] + ('{ ' + inner + ' }' if keep else inner) + text[end + tail.end():]
    return text


def _rows_loops(text):
    """loop_storage_shapes' `__repair_rows: { B } if (C) goto __repair_rows;`: `do { B } while (C);` (`B` for `C` 0)."""
    for m in reversed(list(re.finditer(r'\b(' + IDENT + r'):\s*\{', text))):
        label = m[1]
        if not label.startswith('__repair_') or len(re.findall(r'\bgoto\s+' + label + r'\s*;', text)) != 1:
            continue
        brace = text.index('{', m.end() - 1)
        end = _close(text, brace)
        cond = re.match(r'\s*if\s*\(', text[end:]) if end else None
        if not cond:
            continue
        cond_open = end + cond.end() - 1
        cond_close = _close(text, cond_open, '(', ')')
        jump = re.match(r'\s*goto\s+' + label + r'\s*;', text[cond_close:]) if cond_close else None
        if not jump:
            continue
        condition = text[cond_open + 1:cond_close - 1].strip()
        body = text[brace + 1:end - 1]
        if condition == '0':
            new = '{' + body + '}'
        elif _jumps_out(body):
            continue
        else:
            new = 'do {' + body + '} while (' + condition + ');'
        text = text[:m.start()] + new + text[cond_close + jump.end():]
    return text


def _literal_locals(text):
    """constant_local's `int __repair_literal; … __repair_literal = 0x10; … x * __repair_literal`: the literal again."""
    for name in sorted(set(re.findall(r'\b(__repair_literal\w*)\b', text))):
        decl = re.search(r'(?m)^[ \t]*((?:unsigned\s+)?)int\s+' + name + r'\s*;[ \t]*\n?', text)
        sets = list(re.finditer(r'(?m)^[ \t]*' + name + r'\s*=(?!=)\s*(0[xX][0-9a-fA-F]+|\d+)[uU]?\s*;[ \t]*\n?', text))
        stores = re.findall(r'(?<![\w.])' + name + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + name + r'\b|\b' +
                            name + r'\s*(?:\+\+|--)', text)
        if not decl or len(sets) != 1 or len(stores) != 1:
            continue
        literal = sets[0][1] + ('U' if decl[1] else '')
        if int(sets[0][1], 0) >= 1 << 31 and not decl[1]:
            continue
        # (the assignment must come before every use)
        uses = [u for u in re.finditer(r'(?<![\w.])' + name + r'\b', text)
                if not (decl.start() <= u.start() < decl.end() or sets[0].start() <= u.start() < sets[0].end())]
        if any(u.start() < sets[0].start() for u in uses):
            continue
        for a, b, new in sorted([(u.start(), u.end(), literal) for u in uses] + [(sets[0].start(), sets[0].end(), ''),
                                                                               (decl.start(), decl.end(), '')],
                                reverse=True):
            text = text[:a] + new + text[b:]
    return text


PURE = re.compile(r'(?:[^;{}=()]|\((?:[^;{}=()]|\([^;{}=()]*\))*\)|==|!=|<=|>=)*')


def _single_use_temporaries(text):
    """A `__repair_…` temporary assigned once from an expression with no call or store, read once before anything
    could change that expression, written back where it is read; also `(__repair_addr = E)` never read again."""
    for name in sorted(set(re.findall(r'\b(__repair_(?:addr|value|result|var|cached|hoisted|operand)\w*)\b', text))):
        decl = re.search(r'(?m)^[ \t]*(?P<type>(?:unsigned\s+|signed\s+)?[A-Za-z_]\w*[\s*]*?)\s*\b' + name +
                         r'\s*;[ \t]*\n?', text)
        if not decl:
            continue
        kind = ' '.join(decl['type'].split())
        mentions = [m for m in re.finditer(r'(?<![\w.])' + name + r'\b', text)
                    if not decl.start() <= m.start() < decl.end()]
        # the inline form: `(N = E)` as an operand, N never read
        inline = re.search(r'\(\s*' + name + r'\s*=(?!=)\s*(' + PURE.pattern + r')\)', text)
        if inline and len(mentions) == 1 and _pure(inline[1]):
            text = text[:inline.start()] + '((' + kind + ')(' + inline[1].strip() + '))' + text[inline.end():]
            text = text[:decl.start()] + text[decl.end():] if decl.end() <= inline.start() else text
            continue
        stmt = re.search(r'(?m)^[ \t]*' + name + r'\s*=(?!=)\s*([^;]*);[ \t]*\n?', text)
        if not stmt or len(mentions) != 2 or not _pure(stmt[1]):
            continue
        use = next(m for m in mentions if not stmt.start() <= m.start() < stmt.end())
        between = text[stmt.end():use.start()]
        names = set(re.findall(IDENT, stmt[1]))
        loads = re.search(r'\*|->|\[|M2C_FIELD', stmt[1])
        if use.start() < stmt.end() or re.search(r'\b(goto|return|case|default)\b|' + IDENT + r'\s*:(?!:)|[{}]', between):
            continue
        if any(re.search(r'(?<![\w.>])' + n + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + n + r'\b|\b' + n +
                         r'\s*(?:\+\+|--)', between) for n in names):
            continue
        if loads and (re.search(r'(?<![=!<>])=(?!=)|\+\+|--', between) or _calls(between)):
            continue
        new = '((' + kind + ')(' + stmt[1].strip() + '))'
        text = text[:use.start()] + new + text[use.end():]
        text = text[:stmt.start()] + text[stmt.end():]
        text = text[:decl.start()] + text[decl.end():] if decl.start() < stmt.start() else text
    return text


KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD'}


def _calls(text):
    return [c for c in re.findall(r'\b(' + IDENT + r')\s*\(', text) if c not in KEYWORDS]


def _pure(expr):
    return not _calls(expr) and not re.search(r'(?<![=!<>])=(?!=)|\+\+|--', expr)


def _phase_union(text):
    """`union { void * pointer; s32 value; } __repair_phase_storage;` as the plain pointer local it stands for."""
    decl = re.search(r'(?m)^[ \t]*union\s*\{\s*void\s*\*\s*pointer\s*;\s*s32\s+value\s*;\s*\}\s*'
                     r'(__repair_phase_storage\w*)\s*;', text)
    if not decl:
        return text
    name, local = decl[1], decl[1].replace('_storage', '_pointer')
    text = re.sub(r'\b' + name + r'\.value\s*=(?!=)\s*([^;]+);', lambda m: f'{local} = (void *)({m[1].strip()});', text)
    text = re.sub(r'\b' + name + r'\.value\b', f'((s32) {local})', text)
    text = re.sub(r'\b' + name + r'\.pointer\b', local, text)
    return text.replace(decl.group(0), decl.group(0)[:decl.group(0).index('union')] + f'void *{local};', 1)


VALUE_BLOCK = re.compile(r'\{\s*(?P<type>[A-Za-z_]\w*)\s+(?P<name>__repair_value\w*)\s*;\s*(?P=name)\s*=(?!=)\s*(?P<expr>[^;{}]*);'
                         r'\s*(?P<target>[A-Za-z_]\w*)\s*=(?!=)\s*(?P=name)\s*;\s*\}')


def _value_blocks(text):
    """`{ s32 __repair_value; __repair_value = E; x = __repair_value; }` back to `x = E;`, when `x` has that type."""
    def put(m):
        declared = re.search(r'(?m)^[ \t]*' + m['type'] + r'\s+' + m['target'] + r'\s*;', text)
        return f"{m['target']} = {m['expr'].strip()};" if declared else m[0]
    return VALUE_BLOCK.sub(put, text)


INLINE_HELPER = re.compile(r'(?m)^static\s+__inline__\s+[A-Za-z_]\w*\s+(?P<name>__repair_inline\w*)\s*\('
                           r'(?P<params>[^)]*)\)\s*\{\s*return\s+(?P<body>[^;{}]*);\s*\}[ \t]*\n')


def _inline_helpers(text):
    """A one-line `static __inline__` helper an earlier rewrite made of an expression, written back at its calls (the
    arguments plain names or numbers, so each is evaluated once either way)."""
    for m in list(INLINE_HELPER.finditer(text)):
        params = [re.search(r'([A-Za-z_]\w*)\s*$', p)[1] for p in m['params'].split(',') if p.strip()]
        calls = list(re.finditer(r'\b' + m['name'] + r'\s*\(([^()]*)\)', text[m.end():]))
        args = [[a.strip() for a in c[1].split(',')] for c in calls]
        if not calls or any(len(a) != len(params) or not all(re.fullmatch(r'[A-Za-z_]\w*|-?\d+|0[xX][0-9a-fA-F]+', x)
                                                            for x in a) for a in args):
            continue
        rest = text[m.end():]
        for c, a in reversed(list(zip(calls, args))):
            body = m['body']
            for p, x in zip(params, a):
                body = re.sub(r'\b' + p + r'\b', x, body)
            rest = rest[:c.start()] + '(' + body + ')' + rest[c.end():]
        return _inline_helpers(text[:m.start()] + rest)
    return text


CACHED_POINTER = re.compile(r'(?m)^(?:static\s+)?void\s*\*\s*(?P<name>__repair_cached\w*)\s*=\s*(?P<symbol>[A-Za-z_]\w*)\s*;'
                            r'[ \t]*\n')


def _cached_pointers(text):
    """A file-scope `void *__repair_cached_pointer = D;` copy: its uses read `D` again, as the C did before."""
    for m in list(CACHED_POINTER.finditer(text)):
        rest = re.sub(r'\b' + m['name'] + r'\b', m['symbol'], text[m.end():])
        if re.search(r'\b' + m['symbol'] + r'\s*=(?!=)', text[m.end():]) is None:
            text = text[:m.start()] + rest
    return text


def _scaffolding(text):
    text = re.sub(r'/\*\s*__repair_\w*\s*\*/', '', text)
    for step in (_rows_loops, _unwrap_do_zero, _literal_locals, _single_use_temporaries, _phase_union,
                 _value_blocks, _inline_helpers, _cached_pointers):
        text = step(text)
    return text


STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[A-Za-z_]\w*)\s*=(?!=)(?P<rhs>[^;{}]*);[ \t]*\n')


def _read_before_set(text):
    """A statement that reads a local in the line just before the local's first assignment, swapped back (a random
    statement swap left `t = *(f32 *)((char *)(p) + 0x7C); p = D[i];` in an N64 function's best, reading `p` unset,
    which scored better than the C the game had)."""
    for first in STATEMENT.finditer(text):
        second = STATEMENT.match(text, first.end())
        if not second or second['indent'] != first['indent']:
            continue
        var = second['lhs']
        if var == first['lhs'] or not re.search(r'(?<![\w.>])' + var + r'\b', first['rhs']):
            continue
        # (a local: declared in this function's body, the last unindented line opening a block before it)
        heads = list(re.finditer(r'(?m)^\S[^\n]*\{[ \t]*$', text[:first.start()]))
        body = heads[-1].end() if heads else 0
        before = list(re.finditer(r'(?<![\w.>])' + var + r'\b', text[:first.start()]))
        # (nor one a call may have set through an address: `g(&sp38)` fills sp38..sp40)
        if len(before) != 1 or before[0].start() < body or re.search(r'&\s*[A-Za-z_]', text[body:first.start()]):
            continue
        line = text[text.rfind('\n', 0, before[0].start()) + 1:text.find('\n', before[0].start())]
        if not re.fullmatch(r'[ \t]*[A-Za-z_][\w ]*?[\s*]+' + var + r'\s*;[ \t]*', line):
            continue
        return text[:first.start()] + second.group(0) + first.group(0) + text[second.end():]
    return text


def clean(source: str | None) -> str | None:
    if not source:
        return None
    text = POINTER_CUT.sub(lambda m: f'{m[1]}{m[2]})', source)
    text = TYPE_CAST.sub(lambda m: f'{m[1]}{m[2]}', text)
    text = UNTYPED_REGISTER.sub('', text)
    text = _read_before_set(text)
    text = POINTER_SPLIT.sub(lambda m: f"{m['q']} = (char *)({m['b']}) + {m['k']};", text)
    text = VARIABLE_CUT.sub('', text)
    text = LITERAL_CAST.sub(lambda m: m[0] if int(m[2], 16) <= WIDTH[' '.join(m[1].split())] else m[2], text)
    text = _scaffolding(text)
    return text if text != source else None
