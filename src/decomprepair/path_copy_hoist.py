"""A copy every path through an `if` tree makes, written once after the tree.

The compiler fills the delay slot of each jump to a tree's join with the join's first instruction, and m2c reads those
slots back as a copy on every path, some of them reached by `goto` into a labelled copy:

    if (kind != 1) { if (kind < 2) { cursor = obj; if (kind == 0) { .. } } else { update(obj); cursor = obj; } }
    else { if (owner == 0) { A = 0; goto block_76; } .. block_76: cursor = obj; }
    walk(cursor);

The game wrote `cursor = obj;` once, after the tree. While the copies are there the arms hold values the tree does not
need, and the tree is not read back as the `switch` it came from. The `goto`s are first written out
(`goto_paths_written_out`, after a backward `goto` loop is written as a loop), then:

path_copy_hoist
    The tree is an `if` statement (its `else` chain included) that does not jump, loop or return, where every path runs
    `v = e;`, once or more (`v` a local the tree names nowhere else, `e` a parameter, local or constant the tree does
    not change). Those statements go and one `v = e;` follows the tree.

path_copy_hoist_switch
    The same, with that tree written as the `switch` it came from (`embedded_if_tree_switch`) in the same child.

Measured on a 293-instruction N64 object update (SN gcc 2.8.1, `-G0 -mips3 -O2 -mgas -mfp64`): from the machine
draft's tree the hoisted `switch` took 7285 -> 2850, and with the function's other repairs 0.

Candidate rewrites; the exact judge decides each.
"""
import re

from . import embedded_if_tree_switch, goto_paths_written_out, goto_structure_repairs, goto_walk_break
from .csource import _blank, find
from .pattern_repairs import close

HOIST = 'path_copy_hoist'
SWITCH = 'path_copy_hoist_switch'
FAMILIES = (HOIST, SWITCH)
LIMIT = 6
MAX_BASES = 6

_NAME = r'[A-Za-z_]\w*'
_IF = re.compile(r'(?<![\w])if\s*\(')
_COPY = re.compile(rf'(?m)^[ \t]*(?P<target>{_NAME})\s*=(?!=)\s*(?P<value>{_NAME}|-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*)\s*;')


def _returns(items):
    return any(re.match(r'return\b', item[1]) if item[0] == 'plain' else _returns(item[2]) or _returns(item[3] or [])
               for item in items)


def _always(items, copy):
    """Whether every path through `items` runs the statement `copy`."""
    return any(re.sub(r'\s+', '', item[1]) == copy if item[0] == 'plain'
               else _always(item[2], copy) and _always(item[3] or [], copy) for item in items)


def _own(clean, body_start, name):
    """Whether `name` is a parameter or a local whose address is never taken: nothing else can change it."""
    if re.search(rf'(?<![&\w])&\s*{name}\b', clean):
        return False
    parameters = clean[clean.rfind('(', 0, clean.rfind(')', 0, body_start)) + 1:body_start]
    declared = rf'(?m)^[ \t]*(?!(?:return|goto|else|case)\b)(?:{_NAME}[ \t]+)+[ \t*]*\b{name}\s*(?:;|=(?!=))'
    return bool(re.search(rf'\b{name}\s*[,)]', parameters) or re.search(declared, clean[body_start:]))


def _hoists(source, name):
    """[(start of the tree, the source with one tree's copies written once after it)]."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    last = close(clean, opening, '{', '}') if opening >= 0 else None
    if not last:
        return []
    results, covered = [], {}
    for hit in _IF.finditer(clean, opening, last):
        start = hit.start()
        before = clean[opening + 1:start].rstrip()
        if before and before[-1] not in ';{}':
            continue
        try:
            item, end = embedded_if_tree_switch._if(source, clean, start, last)
        except embedded_if_tree_switch.Bail:
            continue
        region = clean[start:end]
        copies = {}
        for copy in _COPY.finditer(region):
            copies.setdefault((copy['target'], copy['value']), []).append(copy)
        for (target, value), found in copies.items():
            if len(found) < 2 or target == value or any(s <= start < e for s, e in covered.get(target, ())):
                continue
            if len(re.findall(rf'\b{target}\b', region)) != len(found) or not _own(clean, opening, target):
                continue
            if value[0].isalpha() or value[0] == '_':
                changed = rf'\b{value}\b\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{value}\b|\b{value}\s*(?:\+\+|--)'
                if re.search(changed, region) or not _own(clean, opening, value):
                    continue
            statement = f'{target}={value};'
            if _returns([item]) or not _always([item], statement):
                continue
            text = source[start:end]
            for copy in reversed(found):
                a, b = copy.start(), copy.end()
                if region[b:b + 1] == '\n':
                    b += 1
                text = text[:a] + text[b:]
            indent = source[source.rfind('\n', 0, start) + 1:start]
            indent = indent if not indent.strip() else re.match(r'[ \t]*', indent)[0]
            covered.setdefault(target, []).append((start, end))
            results.append((start, source[:start] + text + f'\n{indent}{target} = {value};' + source[end:]))
    return results


def _bases(source, name):
    """The source and its forms with the `goto`s written out (a backward `goto` loop written as a loop first)."""
    loops = [text for _, text in goto_walk_break.variants(source, name)] + [source] + [
        text for family, text in goto_structure_repairs.variants(source, name) if family == 'goto_backward_loop']
    found = []
    for base in loops:
        found.append(base)
        found += [text for _, text in goto_paths_written_out.variants(base, name)]
    # the forms with the fewest jumps left first: a tree with a `goto` in it is not read at all
    return sorted(dict.fromkeys(found), key=lambda text: len(re.findall(r'\bgoto\b', text)))[:MAX_BASES]


def _all(text, name):
    """`text` with every remaining tree's copies hoisted."""
    for _ in range(LIMIT):
        found = _hoists(text, name)
        if not found:
            break
        text = found[0][1]
    return text


def _repeats(source, name):
    """Whether the function writes any copy twice: without that there is nothing to hoist, and no form is worth
    building."""
    span = find(source, name)
    if not span:
        return False
    found = [(m['target'], m['value']) for m in _COPY.finditer(_blank(source[span[0]:span[1]]))]
    return len(found) != len(set(found))


def variants(source, name):
    if not _repeats(source, name):
        return []
    switched, hoisted = [], []
    for base in _bases(source, name):
        for start, text in _hoists(base, name):
            # the tree alone, and with every other tree of the function hoisted in the same child
            hoisted += [(HOIST, _all(text, name)), (HOIST, text)]
            for _, child in embedded_if_tree_switch.variants(text, name):
                if child[:start] == text[:start] and child.startswith('switch', start):
                    switched += [(SWITCH, _all(child, name)), (SWITCH, child)]
    return list(dict.fromkeys(switched))[:LIMIT] + list(dict.fromkeys(hoisted))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
