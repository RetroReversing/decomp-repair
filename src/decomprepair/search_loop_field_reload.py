"""A table search written the way the compiler's loop passes reload it: a counted `for` that re-reads the table field.

A text-measuring routine looked a pair up in a per-character kerning table: a record array reached through a pointer
field of a font (`font->kern`), each 8-byte record holding a pointer to byte pairs and a pair count. Its saved best
(105, KMC GCC 2.7.2) spelt the search as m2c-style `for (;;) { kt = (T *) ((idx * 8) + kern); p = ...pairs + k * 2; k++;
if (p[0] == c) { ... } else if (k < kt->count) { continue; } break; }` behind an `if (count != 0) { k = 0; ... }`, a local
`kern = font->kern;`, a widened copy `c = ch;`, and scaffolding earlier searches had left to keep one pass quiet (a
`volatile` reload of the pair pointer, an `if (x) { A } else { A }` with identical arms, a dead `off = idx * 8` in both
arms of an `if`). It matched (0) once all of that became what the target's registers say a plain program writes:

    if (font->kern != 0) {
        for (k = 0; k < ((T *) font->kern)[idx].count; k++) {
            if (((T *) font->kern)[idx].pairs[k * 2] == ch) { width -= (s8) ((T *) font->kern)[idx].pairs[k * 2 + 1]; break; }
        }
    }

No single piece helps (each alone scored 1278-1735, worse than the 105 it started from), so the family emits the whole
rewrite as one child and the pieces as their own, for a search that already has some of them:

- `record_search_for_loop`: the `for (;;)` search above (with or without its `volatile` pointer read and identical-arm
  `if`) as the counted `for` that tests the record's count in its header, the count guard dropped (jump.c duplicates a
  loop's first test in front of it, which is the pre-loop count check the target has), the pair read through the table
  expression each time;
- the same child with the table pointer local `kern = font->kern;` read through the field wherever it was used (hypothesis:
  the loop pass hoists the re-read field as an invariant load, cse2 then folds it into a register copy of the pre-loop
  load, and that copy is what the target's `move $t0, $v1` is; a local keeps one register and no copy), with the byte
  `ch` compared instead of its widened copy `c` (hypothesis: the hoisted zero-extension of the byte is the target's
  second loop-entry copy), and with the dead `if (x) { off = E; } else { off = E; }` removed.

Each rewrite keeps the meaning: the same records are read in the same order and the same arm runs on the first pair
whose key equals the character. The compiler and the judge decide which spelling the target was."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'record_search_for_loop'
FAMILIES = (FAMILY,)

GUARD = re.compile(r'if\s*\(\s*(?P<count>[^;{}]+?)\s*!=\s*0\s*\)\s*\{\s*(?P<k>' + IDENT + r')\s*=\s*0\s*;\s*for\s*\(\s*;\s*;\s*\)\s*\{')
RECORD = re.compile(r'(?P<kt>' + IDENT + r')\s*=\s*\(\s*(?P<type>' + IDENT + r')\s*\*\s*\)\s*\(\s*\(\s*(?P<idx>' + IDENT
                    + r')\s*\*\s*(?P<size>\d+)\s*\)\s*\+\s*(?P<base>' + IDENT + r')\s*\)\s*;')
POINTER = re.compile(r'(?P<p>' + IDENT + r')\s*=\s*\(\s*(?:u8|unsigned\s+char)\s*\*\s*\)\s*\(\s*(?:'
                     r'\(\s*\*\s*\(\s*\(\s*(?:u8|unsigned\s+char)\s*\*\s*volatile\s*\*\s*\)\s*\(\s*&\s*(?P<kt_a>' + IDENT + r')\s*->\s*(?P<field_a>' + IDENT + r')\s*\)\s*\)\s*\)'
                     r'|(?P<kt_b>' + IDENT + r')\s*->\s*(?P<field_b>' + IDENT + r'))\s*\+\s*\(\s*(?P<k>' + IDENT + r')\s*\*\s*(?P<step>\d+)\s*\)\s*\)\s*;')
TEST = re.compile(r'if\s*\(\s*(?P<p>' + IDENT + r')\s*\[\s*0\s*\]\s*==\s*(?P<cmp>' + IDENT + r')\s*\)\s*\{(?P<act>[^{}]*)\}\s*else\s*if\s*\(\s*(?P<k>' + IDENT
                  + r')\s*<\s*(?P<kt>' + IDENT + r')\s*->\s*(?P<count>' + IDENT + r')\s*\)\s*\{\s*continue\s*;\s*\}\s*break\s*;')
IDENTICAL_ARMS = re.compile(r'if\s*\([^{}]*\)\s*\{(?P<one>[^{}]*)\}\s*else\s*\{(?P<two>[^{}]*)\}')
FIELD_LOCAL = r'(?<![\w.>])(?P<name>{name})\s*=\s*(?P<expr>' + IDENT + r'\s*->\s*' + IDENT + r')\s*;'


def _norm(text):
    return re.sub(r'\s+', ' ', text).strip()


def _search_loop(clean, hit):
    """The parsed `for (;;)` search behind a count guard, or None: its end offset and the pieces the rewrite needs."""
    body_open = hit.end() - 1
    body_end = close(clean, body_open, '{', '}')
    if not body_end:
        return None
    guard_end = re.match(r'\s*\}', clean[body_end:])
    if not guard_end:
        return None
    body = clean[body_open + 1:body_end - 1]
    arms = IDENTICAL_ARMS.match(body.lstrip())
    if arms and _norm(arms['one']) == _norm(arms['two']):
        rest = body.lstrip()[arms.end():]
        triple = arms['one']
    else:
        # the three statements come first, then the test
        record_at = RECORD.search(body)
        pointer_at = POINTER.search(body, record_at.end()) if record_at else None
        if not pointer_at:
            return None
        step_at = re.compile(r'\s*' + re.escape(hit['k']) + r'\s*\+\+\s*;').match(body, pointer_at.end())
        if not step_at or body[:record_at.start()].strip():
            return None
        triple = body[:step_at.end()]
        rest = body[step_at.end():]
    record = RECORD.search(triple)
    pointer = POINTER.search(triple, record.end()) if record else None
    if not record or not pointer:
        return None
    tail = re.compile(r'\s*' + re.escape(hit['k']) + r'\s*\+\+\s*;\s*').fullmatch(triple[pointer.end():])
    if not tail:
        return None
    kt = record['kt']
    field = pointer['field_a'] or pointer['field_b']
    if (pointer['kt_a'] or pointer['kt_b']) != kt or pointer['k'] != hit['k']:
        return None
    test = TEST.fullmatch(rest.strip())
    if not test or test['p'] != pointer['p'] or test['kt'] != kt or test['k'] != hit['k']:
        return None
    if re.search(r'\b(?:break|continue|goto|return|case)\b', test['act']):
        return None
    return {'end': body_end + guard_end.end(), 'k': hit['k'], 'type': record['type'], 'idx': record['idx'], 'size': int(record['size']),
            'base': record['base'], 'field': field, 'count': test['count'], 'step': int(pointer['step']), 'p': pointer['p'],
            'cmp': test['cmp'], 'act': test['act']}


def _rewrite_action(loop, record):
    """The matched arm with each `p[N]` read as the table's pair array indexed through the record expression."""
    def pair(match):
        index = f'{loop["k"]} * {loop["step"]}' + ('' if match['n'] == '0' else f' + {match["n"]}')
        return f'{record}.{loop["field"]}[{index}]'
    return re.sub(r'\b' + re.escape(loop['p']) + r'\s*\[\s*(?P<n>\d+)\s*\]', pair, loop['act']).strip()


def _field_local(part, name):
    """`name = base->field;` when it is the only assignment of `name` and `base` is not written afterwards."""
    text = part.clean[part.opening:part.end]
    found = list(re.finditer(FIELD_LOCAL.format(name=re.escape(name)), text))
    if len(found) != 1 or len(re.findall(r'(?<![\w.>])' + re.escape(name) + r'\s*=(?!=)', text)) != 1:
        return None
    base = re.match(IDENT, found[0]['expr'])[0]
    if re.search(r'(?<![\w.>])' + re.escape(base) + r'\s*(?:[-+*/&|^]|<<|>>)?=(?!=)', text[found[0].end():]) or base == name:
        return None
    return found[0].start() + part.opening, found[0].end() + part.opening, re.sub(r'\s+', '', found[0]['expr'])


def _narrow_source(part, name):
    """`name = byte;` where `byte` is a local declared `u8`: the compare can read the byte itself."""
    text = part.clean[part.opening:part.end]
    found = list(re.finditer(r'(?<![\w.>])' + re.escape(name) + r'\s*=\s*(?P<src>' + IDENT + r')\s*;', text))
    if len(found) != 1 or len(re.findall(r'(?<![\w.>])' + re.escape(name) + r'\s*=(?!=)', text)) != 1:
        return None
    source = found[0]['src']
    declared = re.search(r'(?:\bu8|unsigned\s+char)\s+' + re.escape(source) + r'\s*;', text)
    return source if declared else None


def _dead_arm_assignments(part, keep_before, keep_after):
    """Spans of `if (x) { v = E; } else { v = E; }` whose `v` nothing reads, inside the guard of the search."""
    text = part.clean
    spans = []
    for arms in IDENTICAL_ARMS.finditer(text, part.opening, part.end):
        if not keep_before <= arms.start() < keep_after:
            continue
        one = _norm(arms['one'])
        assign = re.fullmatch(r'(?P<v>' + IDENT + r') = [^;=]+;', one)
        if not assign or _norm(arms['two']) != one:
            continue
        v = assign['v']
        outside = text[part.opening:arms.start()] + text[arms.end():part.end]
        uses = re.findall(r'(?<![\w.>])' + re.escape(v) + r'\b', outside)
        if len(uses) <= 1 and (not uses or re.search(r'\b' + re.escape(v) + r'\s*;', outside)):
            spans.append((arms.start(), arms.end()))
    return spans


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.clean[part.opening:part.end]):
        return []
    out = []
    for hit in GUARD.finditer(part.clean, part.opening, part.end):
        loop = _search_loop(part.clean, hit)
        if not loop:
            continue
        guards = list(re.finditer(r'if\s*\(\s*' + re.escape(loop['base']) + r'\s*!=\s*0\s*\)\s*\{', part.clean[:hit.start()]))
        guard_open = guards[-1] if guards and guards[-1].start() > part.opening else None
        outer_start = guard_open.end() if guard_open else hit.start()
        for inline, narrow in ((False, False), (True, True), (True, False), (False, True)):
            base = loop['base']
            compare = loop['cmp']
            edits = []
            if inline:
                local = _field_local(part, base)
                if not local or not guard_open:
                    continue
                base = local[2]
                edits.append((local[0], local[1], ''))
                edits.append((guard_open.start(), guard_open.end() - 1, f'if ({base} != 0) '))
            if narrow:
                byte = _narrow_source(part, compare)
                if not byte:
                    continue
                compare = byte
            record = f'(({loop["type"]} *) {base})[{loop["idx"]}]'

            action = _rewrite_action(loop, record)
            body = (f'for ({loop["k"]} = 0; {loop["k"]} < {record}.{loop["count"]}; {loop["k"]}++) {{\n'
                    f'    if ({record}.{loop["field"]}[{loop["k"]} * {loop["step"]}] == {compare}) {{ {action} break; }}\n}}')
            edits.append((hit.start(), loop['end'], body))
            if inline and narrow:
                edits += [(a, b, '') for a, b in _dead_arm_assignments(part, outer_start, hit.start())]
            out.append((FAMILY, edit(source, edits)))
    return out
