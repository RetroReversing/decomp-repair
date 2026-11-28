"""goto_ladder_then_else: guards that jump into a later `if`'s then-arm, written as one `if`/`else if` chain.

m2c writes calls that the compiler merged as guards that pick a value and jump into the middle of the last test:

    if (state == 3) { mode = 1; goto block_58; }
    if (state == 2) { mode = 1; goto block_58; }
    if (state != 1) {
        mode = 0;
    block_58:
        draw(obj, mode);
    } else {
        draw(obj, 1);
        attach(obj);
    }

The source had each path make its own call (`if (state == 3) draw(obj, 1); else if (state == 2) draw(obj, 1); else if
(state == 1) { .. } else draw(obj, 0);`) and cross-jumping merged them again. A jump into an arm is a join no source
spelling of the ladder gives, and no family removed it: on a 297-instruction N64 entity-list update (SN gcc 2.8.1,
`-G0 -mips3 -O2`) the ladder written this way was the difference between 2090 and an exact match.
`m2c_goto_join_ladder` needs the last `if` to have no `else` and the label to follow its preceding statements.

Offered when every `goto L;` of the function is one of the consecutive guards directly ahead of `if (C) { [v = K;] L:
RUN } else { OTHER }`, and RUN holds no label, `case`, `goto` or declaration. Each guard body is `goto L;`, or one
assignment to `v` and the `goto`. When `v` only carries a number to RUN, each copy of RUN has the number written in
place of `v`; the other children keep the assignment in front of each copy. Each is offered as written (`if (C) RUN
else OTHER`) and with the last test the other way round (`if (!C) OTHER else RUN`), which the target's branch order
decides. A candidate rewrite; the exact judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'goto_ladder_then_else'
FAMILIES = (FAMILY,)
LIMIT = 8

_IF = re.compile(r'\bif\s*\(')
_LABEL = re.compile(r'(?<=[;{}])\s*(?P<label>[A-Za-z_]\w*)\s*:(?!:)')
# a label at the head of a block, at most one assignment ahead of it
_HEAD = re.compile(r'\{\s*(?:[A-Za-z_]\w*\s*=(?!=)\s*[^;{}]+?;\s*)?(?P<label>[A-Za-z_]\w*)\s*:(?!:)')
_GUARD = re.compile(r'\{\s*(?:(?P<v>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<k>[^;{}]+?)\s*;\s*)?goto\s+(?P<label>\w+)\s*;\s*\}')
_NUMBER = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*')


def _if_at(clean, at):
    """(condition span, brace of the arm, its closer) of a braced `if` starting at `at`, or None."""
    match = _IF.match(clean, at)
    if not match:
        return None
    paren = close(clean, match.end() - 1)
    if not paren:
        return None
    brace = re.compile(r'\s*\{').match(clean, paren)
    if not brace:
        return None
    end = close(clean, brace.end() - 1, '{', '}')
    return ((match.end(), paren - 1), brace.end() - 1, end) if end else None


def _guards(clean, start, stop, label):
    """The consecutive `if (a) { [v = k;] goto label; }` statements that end at `stop`, first one first."""
    found = []
    ifs = [m.start() for m in _IF.finditer(clean, start, stop)]
    edge = stop
    for at in reversed(ifs):
        parts = _if_at(clean, at)
        if not parts or parts[2] > edge or clean[parts[2]:edge].strip():
            continue
        body = _GUARD.fullmatch(clean, parts[1], parts[2])
        if not body or body['label'] != label or re.search(r'\belse\s*$', clean[start:at]):
            break
        found.append((at, parts[0], body))
        edge = at
    return found[::-1]


def _arm(text):
    return '{\n' + text.strip('\n').rstrip() + '\n}'


def variants(source, name):
    span = find(source, name)
    if span is None:
        return []
    clean = _blank(source)
    start, stop = span
    out = []
    for label in _HEAD.finditer(clean, start, stop):
        tag = label['label']
        if tag == 'default' or not re.search(rf'\bgoto\s+{tag}\s*;', clean[start:stop]):
            continue
        # the `if` whose then-arm the label heads: the nearest one before it with that brace
        holder = None
        for match in reversed(list(_IF.finditer(clean, start, label.start()))):
            parts = _if_at(clean, match.start())
            if parts and parts[1] == label.start():
                holder = (match.start(), parts)
                break
        if holder is None:
            continue
        at, (condition, brace, end) = holder
        head = clean[brace + 1:label.start('label')].strip()
        first = re.fullmatch(r'(?:([A-Za-z_]\w*)\s*=(?!=)\s*([^;{}]+?)\s*;)?', head)
        other = re.compile(r'\s*else\s*\{').match(clean, end)
        if not first or not other:
            continue
        other_end = close(clean, other.end() - 1, '{', '}')
        if not other_end:
            continue
        run = (label.end(), end - 1)
        if re.search(r'\bgoto\b|\bcase\b|\bdefault\b', clean[run[0]:run[1]]) or _LABEL.search(clean, run[0] - 1, run[1]):
            continue
        if re.search(r'(?<=[;{}])\s*(?:const\s+|volatile\s+|register\s+|struct\s+)*(?!return\b|else\b)[A-Za-z_]\w*[\s*]+'
                     r'[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?(?:=[^;]*)?;', clean[run[0] - 1:run[1]]):
            continue
        guards = _guards(clean, start, at, tag)
        jumps = len(re.findall(rf'\bgoto\s+{tag}\s*;', clean[start:stop]))
        if not guards or jumps != len(guards) or re.search(r'\belse\s*$', clean[start:guards[0][0]]):
            continue
        local = first[1]
        if any(body['v'] != local for _, _, body in guards):
            continue
        values = [source[body.start('k'):body.end('k')] if local else '' for _, _, body in guards]
        values.append(source[brace + 1:label.start('label')].split('=', 1)[1].rsplit(';', 1)[0].strip() if local else '')
        conditions = [source[a:b] for _, (a, b), _ in guards]
        last = source[condition[0]:condition[1]]
        text = source[run[0]:run[1]]
        else_arm = source[other.end() - 1:other_end]
        spellings = []
        substituted = local and _carries_only(clean, start, stop, local, guards, (brace, label.start('label')), run, values)
        if substituted:
            spellings.append(([re.sub(rf'(?<![\w.>]){local}\b', value.strip(), text) for value in values], True))
        prefixes = [f'{local} = {value.strip()};\n' if local else '' for value in values]
        spellings.append(([prefix + text.strip('\n') for prefix in prefixes], False))
        for arms, drop in spellings:
            chain = ''.join(f'if ({test}) {_arm(arm)} else ' for test, arm in zip(conditions, arms))
            for flipped in (True, False):
                tail = (f'if ({last}) {_arm(arms[-1])} else {else_arm}' if not flipped
                        else f'if ({negate(last)}) {else_arm} else {_arm(arms[-1])}')
                child = source[:guards[0][0]] + chain + tail + source[other_end:]
                if drop:
                    child = _drop_declaration(child, name, local)
                out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


def _carries_only(clean, start, stop, local, guards, head, run, values):
    """Whether `local` is a plain local set only to numbers on these paths and read only inside the run."""
    if not all(_NUMBER.fullmatch(value.strip()) for value in values):
        return False
    body = clean.find('{', start)
    declared = re.search(rf'(?<=[;{{}}])\s*[A-Za-z_]\w*[\s*]+{local}\s*;', clean[body:stop])
    if body < 0 or not declared:
        return False
    declaration = (body + declared.start(), body + declared.end())
    sets = [(g[2].start(), g[2].end()) for g in guards] + [head, declaration]
    if re.search(rf'(?<![\w.>]){local}\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--|(?<!&)&)\s*{local}\b',
                 clean[run[0]:run[1]]):
        return False
    return all(any(a <= use.start() < b for a, b in sets + [run])
               for use in re.compile(rf'(?<![\w.>]){local}\b').finditer(clean, body, stop))


def _drop_declaration(source, name, local):
    span = find(source, name)
    if span is None:
        return source
    if len(re.findall(rf'(?<![\w.>]){local}\b', _blank(source)[span[0]:span[1]])) != 1:
        return source
    match = re.compile(rf'\n[ \t]*[A-Za-z_]\w*[ \t*]+{local}[ \t]*;').search(source, span[0], span[1])
    return source[:match.start()] + source[match.end():] if match else source


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
