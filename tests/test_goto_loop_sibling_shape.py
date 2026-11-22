"""goto_loop_sibling_shape: a `goto` row loop as a `do`/`while`, with its commuted last statement written like its siblings.

Shape of a 167-instruction KMC function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2 -fno-strength-reduce`): the third
coordinate of each vertex read `z = off[2] + (scale[2] * p[2]);` beside two `(p[k] * scale[k]) + off[k]` statements.
The `do`/`while` alone 35 -> 50, the sibling order alone 60, both 25 (and 0 with `chain_weight_scope`'s scopes)."""
from decomprepair import goto_loop_sibling_shape as shape

SOURCE = '''typedef struct { f32 scale[3]; f32 offset[3]; } Frame;
void f(f32 *coords, u16 *packed, Frame *frame, s32 n)
{
  s32 i;
  i = 0;
  if (n > 0)
  {
    __repair_rows:
    {
      f32 z;
      coords[0] = (packed[0] * frame->scale[0]) + frame->offset[0];
      coords[1] = (packed[1] * frame->scale[1]) + frame->offset[1];
      z = frame->offset[2] + (frame->scale[2] * packed[2]);
      i++;
      packed += 3;
      coords[2] = z;
      coords += 3;
    }

    if (i < n)
    {
      goto __repair_rows;
    }
  }
}
'''


def test_the_loop_and_the_commuted_statement_are_one_child_first():
    out = shape.variants(SOURCE, 'f')
    assert out[0][0] == 'goto_loop_sibling_shape'
    whole = out[0][1]
    assert 'z = (packed[2] * frame->scale[2]) + frame->offset[2];' in whole
    assert 'do {' in whole and '} while (i < n);' in whole
    assert 'goto' not in whole and '__repair_rows' not in whole
    assert 'coords[2] = z;' in whole


def test_each_half_alone_follows():
    out = [text for _, text in shape.variants(SOURCE, 'f')]
    assert len(out) == 3
    fix_only = next(text for text in out if '__repair_rows:' in text)
    assert 'z = (packed[2] * frame->scale[2]) + frame->offset[2];' in fix_only
    loop_only = next(text for text in out if 'do {' in text and 'frame->offset[2] + (frame->scale[2] * packed[2])' in text)
    assert '} while (i < n);' in loop_only


def test_a_store_written_directly_is_fixed_too():
    source = SOURCE.replace('      z = frame->offset[2] + (frame->scale[2] * packed[2]);\n', '').replace(
        '      coords[2] = z;\n', '      coords[2] = frame->offset[2] + (frame->scale[2] * packed[2]);\n').replace('      f32 z;\n', '')
    whole = shape.variants(source, 'f')[0][1]
    assert 'coords[2] = (packed[2] * frame->scale[2]) + frame->offset[2];' in whole


def test_siblings_that_differ_by_more_than_operand_order_offer_nothing():
    source = SOURCE.replace('frame->offset[2] + (frame->scale[2] * packed[2])', 'frame->offset[1] + (frame->scale[2] * packed[2])')
    assert shape.variants(source, 'f') == []
    assert shape.variants('void g(void) { }', 'g') == []


def test_a_group_already_in_the_siblings_order_offers_nothing():
    natural = SOURCE.replace('frame->offset[2] + (frame->scale[2] * packed[2])', '(packed[2] * frame->scale[2]) + frame->offset[2]')
    assert shape.variants(natural, 'f') == []
