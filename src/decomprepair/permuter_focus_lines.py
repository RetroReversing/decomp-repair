"""Keep decomp-permuter's randomizer on the C lines a caller says matter (stdlib only, like the generator beside it).

The caller knows which lines of the source the compiler ties to the instructions that differ (decompdecomp's
source_lines.py). decomp-permuter already has a notion of where a rewrite may act: a `Region` of node indices, picked
from `PERM_RANDOMIZE` pragmas and otherwise the whole function. `install` swaps the picker for one that, a share of the
time, returns a region around one of those lines and its neighbours, so rewrites land where the difference is.
Everything else is left alone: a source with its own pragmas keeps them, the rest of the time the whole function is
fair game, and a line that can't be found is dropped, so no focus is the same as before.
"""
import difflib
import re

SHARE = 0.7  # the chance a rewrite is confined to a focus line (the rest of the time: the whole function, as before)
NEIGHBOURS = 1  # lines either side of the chosen one that stay in the region (statements to reorder against)
_BLOCKS = {"Compound", "FuncDef", "If", "While", "For", "DoWhile", "Switch", "Case", "Default", "Label"}
_NOISE = re.compile(r"\s+")


def _entries(text: str) -> list[tuple[int, str]]:
    return [(number, _NOISE.sub("", line)) for number, line in enumerate(text.split("\n"), 1) if line.strip()]


def line_map(original: str, final: str) -> dict[int, int]:
    """{line of `original`: line of `final`} for the lines the generator's reading of the source left as they were
    (it drops comments and directives and expands some macros): found by aligning the non-blank lines."""
    before, after = _entries(original), _entries(final)
    matcher = difflib.SequenceMatcher(None, [text for _, text in before], [text for _, text in after], autojunk=False)
    found: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for offset in range(i2 - i1):
                found[before[i1 + offset][0]] = after[j1 + offset][0]
    return found


def lines_in_unit(focus, original: str, final: str, seam_line: int) -> set[int]:
    """The parsed unit's line numbers for the caller's `focus` lines, `final` starting on the line after `seam_line`."""
    mapped = line_map(original, final)
    return {seam_line + mapped[line] for line in focus if isinstance(line, int) and line in mapped}


def _walk(node):
    yield node
    for _, child in node.children():
        yield from _walk(child)


def line_spans(top, indices, lines) -> dict[int, tuple[int, int]]:
    """{line: (first start index, last end index)} of the statements and expressions that begin on each of `lines`."""
    spans: dict[int, tuple[int, int]] = {}
    for node in _walk(top):
        coord = getattr(node, "coord", None)
        if coord is None or coord.line not in lines or type(node).__name__ in _BLOCKS:
            continue
        if node not in indices.starts or node not in indices.ends:
            continue
        low, high = spans.get(coord.line, (indices.starts[node], indices.ends[node]))
        spans[coord.line] = (min(low, indices.starts[node]), max(high, indices.ends[node]))
    return spans


class Focus:
    """The lines (in the parsed unit) a job's rewrites favour; empty means no focus."""

    def __init__(self, lines=(), share: float = SHARE):
        self.lines, self.share = set(lines), share

    def region(self, top, indices, random, region_type):
        """A region around one focus line and its neighbours, or None (use the ordinary one)."""
        if not self.lines or random.random() >= self.share:
            return None
        spans = line_spans(top, indices, self.lines)
        if not spans:
            return None
        chosen = random.choice(sorted(spans))
        around = line_spans(top, indices, set(range(chosen - NEIGHBOURS, chosen + NEIGHBOURS + 1)))
        low, high = min(a for a, _ in around.values()), max(b for _, b in around.values())
        return region_type(low - 1, high + 1, indices)


def install(randomizer_module, focus: Focus) -> None:
    """Make decomp-permuter's `get_randomization_region` ask `focus` first, unless the source marks its own region."""
    original = getattr(randomizer_module, "get_randomization_region", None)
    if original is None or getattr(original, "focused", False):
        return

    def get_randomization_region(top, indices, random):
        base = original(top, indices, random)
        if not base.is_unbounded():
            return base
        return focus.region(top, indices, random, type(base)) or base

    get_randomization_region.focused = True
    randomizer_module.get_randomization_region = get_randomization_region
