"""square_sum_steps: a squared distance written as one expression, written back as in-place steps."""
import shutil

import pytest
from test_clean_rewrite import run

from decomprepair import registry
from decomprepair import square_sum_steps as m

SEARCH = """s32 nearest(s16 *xs, s16 *ys, s32 x, s32 y, s32 range)
{
  s32 dx;
  s32 dy;
  s32 i;
  s32 pick;
  u32 dist;
  u32 best;
  pick = -1;
  dx = 0;
  best = ((u32) (range * range)) >> 0xC;
  for (i = 0; i < 4; i++)
  {
    do { dx = x - xs[i]; } while (0);
    do { dy = y - ys[i]; } while (0);
    do { do { dist = (((u32) (dx * dx)) >> 0xC) + (((u32) (dy * dy)) >> 0xC); } while (0); } while (0);
    if (dist < best)
    {
      pick = i;
      best = dist;
      dx = 1;
    }
  }
  return pick + (best << 4);
}
"""

CALLS = ['nearest((short[]){-300, 90, 4000, 7}, (short[]){5, -90, 2, 8000}, 100, -50, 9000)',
         'nearest((short[]){-300, 90, 4000, 7}, (short[]){5, -90, 2, 8000}, 0, 0, 100)']


def test_first_child_folds_the_difference_and_opens_the_fences():
    family, text = m.variants(SEARCH, 'nearest')[0]
    assert family == m.FAMILY
    assert 'dist = x - xs[i]; dist *= dist; dist >>= 0xC;' in text
    assert 'dy *= dy; dist += ((u32) dy) >> 0xC;' in text
    assert 'best = range * range; best >>= 0xC;' in text
    assert 'while (0)' not in text


@pytest.mark.skipif(shutil.which('cc') is None, reason='no host C compiler')
def test_children_compute_what_the_source_did(tmp_path):
    expected = run(tmp_path, SEARCH, CALLS)
    children = m.variants(SEARCH, 'nearest')
    assert children
    for _, text in children:
        assert run(tmp_path, text, CALLS) == expected


def test_a_difference_read_again_is_not_squared_in_place():
    source = SEARCH.replace('return pick + (best << 4);', 'return pick + dy;')
    assert not any('dy *= dy' in text for _, text in m.variants(source, 'nearest'))


def test_registered():
    assert registry.get('square_sum_steps')
