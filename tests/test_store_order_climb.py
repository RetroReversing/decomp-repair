import re

from decomprepair.store_order_climb import blocks, climb, moves

LINES = [f'    p->f{i:X} = {v};' for i, v in zip(range(0, 40, 4), (5, 9, 1, 7, 3, 8, 2, 6, 4, 10))]
SOURCE = 'void init(Rec *p) {\n' + '\n'.join(LINES) + '\n}\n'
WANT = sorted(LINES, key=lambda line: int(re.search(r'= (\d+);', line)[1]))


def distance(text):
    """The number of statement pairs out of the order WANT (a stand-in for the byte judge's score)."""
    got = [WANT.index(line) for line in text.splitlines() if line.strip().startswith('p->')]
    return sum(got[a] > got[b] for a in range(len(got)) for b in range(a + 1, len(got)))


def test_a_long_block_is_found_and_has_single_moves():
    assert len(blocks(SOURCE, 'init')[0]) == 10
    assert moves(SOURCE, 'init') and all(m != SOURCE for m in moves(SOURCE, 'init'))


def test_a_short_block_is_not_a_climb_target():
    short = 'void init(Rec *p) {\n' + '\n'.join(LINES[:4]) + '\n}\n'
    assert not blocks(short, 'init')


def test_the_climb_reaches_the_target_order_one_move_at_a_time():
    best, score, calls = climb(SOURCE, 'init', distance, budget=2000)
    assert score == 0 and distance(best) == 0 and calls <= 2000


def test_a_candidate_that_does_not_compile_is_skipped_and_the_budget_is_kept():
    best, score, calls = climb(SOURCE, 'init', lambda text: None if text != SOURCE else 9, budget=40)
    assert best == SOURCE and score == 9 and calls <= 40


def test_a_source_that_does_not_compile_returns_unchanged():
    assert climb(SOURCE, 'init', lambda text: None) == (SOURCE, None, 1)
