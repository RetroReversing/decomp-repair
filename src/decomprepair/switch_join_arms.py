"""Which switch arm carries a shared join block, where the arms sit, and which constants the joining arms assign.

m2c writes a `switch` whose arms set a value and meet at one block as

    switch (k) {
    case 0x12: v = 0x13;
    join: if (t == v) { case 6: case 8: return 1; } return 0;
    case 0x20: v = 0x21; goto join;
    default: return 0;
    }

The block is written once, inside whichever arm the decompiler met it in first, and the other arms `goto` it. The
compiler lays the arms out in the order the source has them, the block directly after the arm that falls into it, so
a game whose source had `case 0x12: v = 19; goto join; default: return 0; case 0x20: v = 33; join: ...` compiles to
other bytes than the draft: the draft's arm is first and falls into the block, and no reorder of whole arms
(`switch_layout`) moves the block itself. Two kinds of edit decide it, and a plain statement-order search finds
neither, because each is a different program until both are made:

- `switch_join_host`: the block moves into another arm that ends with `goto join;` (that arm now falls into it and the
  arm that held it jumps), and the arms are laid out in each order the compiler could have had them (all of them up to
  four arms; a rotation and the reverse beyond). The target's jump table, when the caller has it (`tables`: each
  one's lowest case value and the address every case enters), says which arm the block belongs to (the arm whose
  address is the highest one below where the block's own cases enter) and which order the arms with a body of their
  own sit in; a bare `return`/`break` arm is not ordered by it (the compiler merges those tails, so their address is
  the shared tail's).
- `switch_join_values`: the constants assigned in two arms that reach the same join exchanged. The two programs differ
  only in which case number leads to which constant, which a compiled jump table shows (the instructions are
  identical, only the table's data differs, and the judge's rows are empty); `linked_switch_labels` then relabels the
  cases from the table's differences.

Both are source hypotheses: the judge decides, and every other statement of every arm is kept as it was."""
import re
from collections import Counter
from itertools import permutations

from .integer_repair_support import IDENT, INTEGER, view
from .pattern_repairs import close
from .switch_tables import LABEL, value

FAMILY_HOST = 'switch_join_host'
FAMILY_VALUES = 'switch_join_values'
FAMILIES = (FAMILY_HOST, FAMILY_VALUES)
LIMIT = 48
LITERAL = r"(?:-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*|'(?:\\.|[^'\\])')"
_STATEMENT_LABEL = re.compile(rf'(?<![\w$.])({IDENT})\s*:(?!:)')
_TERMINAL = re.compile(rf'(?:\bbreak|\bcontinue|\breturn\b[^;{{}}]*|\bgoto\s+({IDENT}))\s*;\s*$')
_DECLARATION = re.compile(rf'\b(?:{INTEGER}|void|float|double)\s*\**\s*{IDENT}\s*[=;\[,]')


def _terminal(clean):
    """The final statement of an arm's text when it leaves the arm for good, else None (`if (x) return;` does not)."""
    text = clean.rstrip()
    hit = _TERMINAL.search(text)
    if not hit:
        return None
    before = text[:hit.start()].rstrip()
    if before and before[-1] not in ';{}:' or text[:hit.start()].count('{') != text[:hit.start()].count('}'):
        return None
    return hit


def _switches(part):
    """[(arms)] for each switch of the function: `arms` are (start, stop, [case numbers; None for default]) of
    whole case groups (grouped labels travel with their body), or None when the labels are not plain."""
    clean = part.clean
    found = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        condition = close(clean, part.opening + switch.end() - 1)
        if not condition:
            continue
        gap = clean[condition:part.end]
        brace = condition + len(gap) - len(gap.lstrip())
        if clean[brace:brace + 1] != '{' or not (end := close(clean, brace, '{', '}')):
            continue
        inside = clean[brace + 1:end - 1]
        labels = [hit for hit in LABEL.finditer(part.source, brace + 1, end - 1)
                  if clean[brace + 1:hit.start()].count('{') == clean[brace + 1:hit.start()].count('}')
                  and clean[hit.start():hit.start() + 4] in ('case', 'defa')]
        every = [hit for hit in re.finditer(r'\b(?:case|default)\b', inside)
                 if inside[:hit.start()].count('{') == inside[:hit.start()].count('}')]
        if len(labels) != len(every) or len(labels) < 2 or clean[brace + 1:labels[0].start()].strip():
            continue
        arms, start, numbers = [], labels[0].start(), []
        try:
            for index, label in enumerate(labels):
                numbers.append(None if label[1] is None else value(label[1]))
                stop = labels[index + 1].start() if index + 1 < len(labels) else end - 1
                if clean[label.end():stop].strip():
                    arms.append((start, stop, numbers))
                    start, numbers = stop, []
        except (ValueError, SyntaxError, TypeError):
            continue
        if numbers or len(arms) < 2 or len(arms) > 6:
            continue
        found.append((brace, end, arms))
    return found


def _joins(clean, arm):
    """[(label, position of the label in the arm)] of the labelled statements directly in the arm (not nested)."""
    text = clean[arm[0]:arm[1]]
    found = []
    for hit in _STATEMENT_LABEL.finditer(text):
        if hit[1] in ('case', 'default') or text[:hit.start()].count('{') != text[:hit.start()].count('}'):
            continue
        before = text[:hit.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        found.append((hit[1], hit.start()))
    return found


def _goto_end(clean, arm, label):
    """Where the arm's last statement `goto label;` starts, or None when the arm does not end with it."""
    text = clean[arm[0]:arm[1]]
    hit = _terminal(text)
    if hit and hit[1] == label:
        return hit.start()
    return None


def _orders(count, wanted=None):
    if count <= 4:
        every = [list(order) for order in permutations(range(count))]
    else:
        every = [list(range(count))] + [list(range(rotation, count)) + list(range(rotation)) for rotation in range(1, count)]
        every += [list(reversed(range(count)))]
    every.sort(key=lambda order: order != list(range(count)))
    return [order for order in every if wanted is None or wanted(order)]


def _addresses(tables, arms, nested):
    """(address of each arm, highest-address arm below the nested cases' entry) from the target's jump table, or None.

    Only arms whose body is more than a bare `return`/`break` get an address: the compiler merges those tails."""
    for low, targets in tables or ():
        if len(targets) < 2:
            continue
        common = Counter(targets).most_common(1)[0][0]

        def entry(number, low=low, targets=targets):
            return targets[number - low] if low <= number < low + len(targets) else None
        result = []
        for _, _, numbers, bare in arms:
            known = [entry(n) for n in numbers if n is not None]
            if bare or not known or any(item is None for item in known):
                result.append(None)
            else:
                result.append(min(known))
        wanted = [entry(n) for n in nested]
        if not wanted or any(item is None for item in wanted) or common in wanted:
            continue
        return result, min(wanted)
    return None


def _host_variants(source, part, brace, end, arms, tables):
    clean = part.clean
    chunks = [source[start:stop] for start, stop, _ in arms]
    if any(_DECLARATION.search(clean[start:stop]) for start, stop, _ in arms):
        return []
    results = []
    for host, arm in enumerate(arms):
        for label, at in _joins(clean, (arm[0], arm[1])):
            core = chunks[host].rstrip()
            block = core[at:]
            if not _terminal(clean[arm[0] + at:arm[1]]) or _DECLARATION.search(clean[arm[0] + at:arm[1]]):
                continue
            nested = [value(hit[1]) for hit in LABEL.finditer(source, arm[0] + at, arm[1])
                      if hit[1] is not None and clean[arm[0] + at:hit.start()].count('{') > clean[arm[0] + at:hit.start()].count('}')]
            for other, group in enumerate(arms):
                if other == host:
                    continue
                goto = _goto_end(clean, group, label)
                if goto is None:
                    continue
                keep = chunks[:]
                moved = chunks[other].rstrip()
                keep[other] = moved[:goto] + block + chunks[other][len(moved):]
                keep[host] = core[:at] + f'goto {label};' + chunks[host][len(core):]
                wanted = None
                if tables:
                    from_table = _addresses(tables, [(a, b, n, _bare(clean[a:b])) for a, b, n in arms], nested)
                    if from_table:
                        addresses, entry = from_table
                        below = [item for item in addresses if item is not None and item < entry]
                        if not below or addresses[other] != max(below):
                            continue  # the target's table puts the block under another arm
                        placed = [i for i, item in enumerate(addresses) if item is not None]

                        def wanted(order, placed=placed, addresses=addresses):
                            ranks = [i for i in order if i in placed]
                            return all(addresses[a] <= addresses[b] for a, b in zip(ranks, ranks[1:]))
                for order in _orders(len(arms), wanted):
                    text = ''.join(keep[i] for i in order)
                    results.append((FAMILY_HOST, source[:arms[0][0]] + text + source[arms[-1][1]:]))
    return results


def _bare(clean):
    return bool(re.fullmatch(r'\s*(?:(?:case\s+[^:]+|default)\s*:\s*)*(?:break|return\b[^;{}]*)\s*;\s*', clean))


def _value_variants(source, part, arms):
    clean = part.clean
    feeds = {}  # label -> [(arm index, variable, literal start, literal end)] of the arms that reach it
    for index, arm in enumerate(arms):
        cleaned = clean[arm[0]:arm[1]]
        reaches = [(label, at) for label, at in _joins(clean, arm)]
        stops = [(label, at) for label, at in reaches]
        ends = _terminal(cleaned)
        if ends and ends[1]:
            stops.append((ends[1], ends.start()))
        for label, at in stops:
            hit = re.search(rf'(?<![\w.>])({IDENT})\s*=(?!=)\s*({LITERAL})\s*;\s*$', cleaned[:at])
            if hit and cleaned[:hit.start()].count('{') == cleaned[:hit.start()].count('}'):
                feeds.setdefault(label, []).append((index, hit[1], arm[0] + hit.start(2), arm[0] + hit.end(2)))
    results = []
    for group in feeds.values():
        for first in range(len(group)):
            for second in range(first + 1, len(group)):
                (a, name_a, start_a, end_a), (b, name_b, start_b, end_b) = group[first], group[second]
                if a == b or name_a != name_b or source[start_a:end_a] == source[start_b:end_b]:
                    continue
                text = source
                for start, stop, replacement in sorted(((start_a, end_a, source[start_b:end_b]),
                                                        (start_b, end_b, source[start_a:end_a])), reverse=True):
                    text = text[:start] + replacement + text[stop:]
                results.append((FAMILY_VALUES, text))
    return results


def variants(source, name, tables=()):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    results = []
    for brace, end, arms in _switches(part):
        results += _host_variants(source, part, brace, end, arms, tables)
        results += _value_variants(source, part, arms)
    return [item for item in dict.fromkeys(results) if item[1] != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'tables')}
