"""compose: independent children of one source merged into one, for a search over combined steps.

The commonest blocker in a hand match: two or three edits that are each neutral or worse alone and exact together (a
loop's preheader role and a flag's local, a guard collapse and a merged local). A greedy search keeps only the child
that improves and never takes the first of them; a family written to offer that exact combination is the only thing
that finds it today. This is the general form: the caller keeps the most promising children that did NOT improve
(`rank`: fewest differing rows of the judge's diff first, then score; a few per family so one family's variants cannot
crowd the rest out) and asks for their compositions (`compositions`): pairs of children from different families whose
edits touch different tokens of the parent, then triples whose three pairs all merged. Each composition is the
parent with every child's edits applied (`merge`); two edits that overlap are alternatives, not independent, and are
never merged.

Pure: nothing here compiles or judges, and the caller's judge decides. The token-level merge is what the
match-function skill's prove_chain used since 0.5.6xx (moved here so the app's searches share it)."""
import difflib
import itertools
import re

TOKEN = re.compile(r"[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+|\s+|.", re.S)
PER_FAMILY = 2      # children of one family kept for composing: its variants are alternatives of one edit
TOP = 8             # children composed: 28 pairs and 56 triples at most
LIMIT = 120         # compositions returned


def edits(base, child):
    """(base tokens, [(start, end, replacement tokens)]): the child as token edits of `base`."""
    left, right = TOKEN.findall(base), TOKEN.findall(child)
    ops = difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
    return left, [(a, b, right[c:d]) for tag, a, b, c, d in ops if tag != 'equal']


def _apply(tokens, found):
    found = sorted(found, key=lambda e: (e[0], e[1]))
    for (a1, b1, _), (a2, b2, _) in zip(found, found[1:]):
        if a2 < b1 or (a1 == a2 and (a1 == b1 or a2 == b2)):
            return None
    out, at = [], 0
    for a, b, replacement in found:
        out += tokens[at:a] + replacement
        at = b
    return ''.join(out + tokens[at:])


def merge(base, children):
    """One source with every child's edits of `base`, or None when two of them touch the same tokens (or insert at
    the same place), or a child does not differ from `base`: then the merge would be a guess."""
    tokens, found = TOKEN.findall(base), []
    for child in children:
        _, own = edits(base, child)
        if not own:
            return None
        found += own
    return _apply(tokens, found)


def rank(items, top=TOP, per_family=PER_FAMILY):
    """The children worth composing, best first. `items`: [(rows, score, family, child)], `rows` the number of the
    judge's differing rows (None: unknown, ranked after every known count) and `score` the judge's (None: did not
    compile, dropped). Fewest rows first, then score: agents found the row count a far better guide to the child
    that is half of a combination than the total, which an edit's moved rows inflate. At most `per_family` each."""
    usable = [item for item in items if item[1] is not None]
    usable.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0, item[1]))
    out, per = [], {}
    for item in usable:
        if per.get(item[2], 0) >= per_family:
            continue
        per[item[2]] = per.get(item[2], 0) + 1
        out.append(item)
        if len(out) >= top:
            break
    return out


def compositions(base, ranked, limit=LIMIT, triples=True):
    """[(families joined by '+', merged source)]: pairs of `ranked` children ([(rows, score, family, child)] or
    [(family, child)], best first) from different families whose edits are independent, the pairs of the best
    children first; then triples whose three pairs all merged. Never `base` itself, never one source twice."""
    kids = [(item[-2], item[-1]) for item in ranked]
    tokens = TOKEN.findall(base)
    own = []
    for _, child in kids:
        found = edits(base, child)[1]
        own.append(found or None)
    out, seen, merged_pairs = [], {base}, set()
    pairs = sorted(itertools.combinations(range(len(kids)), 2), key=lambda p: (p[0] + p[1], p))
    for i, j in pairs:
        if kids[i][0] == kids[j][0] or own[i] is None or own[j] is None:
            continue
        text = _apply(tokens, own[i] + own[j])
        if text is None:
            continue
        merged_pairs.add((i, j))
        if text not in seen:
            seen.add(text)
            out.append((f'{kids[i][0]}+{kids[j][0]}', text))
            if len(out) >= limit:
                return out
    if not triples:
        return out
    for group in sorted(itertools.combinations(range(len(kids)), 3), key=lambda g: (sum(g), g)):
        if not all(pair in merged_pairs for pair in itertools.combinations(group, 2)):
            continue
        text = _apply(tokens, [e for i in group for e in own[i]])
        if text is None or text in seen:
            continue
        seen.add(text)
        out.append(('+'.join(kids[i][0] for i in group), text))
        if len(out) >= limit:
            break
    return out
