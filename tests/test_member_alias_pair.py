"""A raw-offset word store as a structure member beside a one-member record global.

Synthetic shape of the tail of a display-list function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): two plain
globals advanced after stores through a cursor pointer, and a third global read for the call that follows. The
exact-judge replay is in decompdecomp's tests (it needs the compiler): 60 -> 0 on the 144-instruction function."""
from decomprepair import member_alias_pair as m

SOURCE = '''extern s32 D_A;
extern s32 D_B;
extern volatile s32 D_V;
extern void *D_P;
void draw(s32 arg0)
{
  void *tail;
  void *cur;
  s32 count;
  tail = D_P;
  cur = D_P;
  *((s32 *) (((char *) tail) + 0)) = 1;
  *((s32 *) (((char *) cur) + 4)) = D_V;
  D_A = D_A + 8;
  count = D_B;
  func(arg0, count);
}
'''


def _texts(source=SOURCE):
    found = m.variants(source, 'draw')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_a_store_becomes_a_member_and_the_global_a_one_member_record():
    texts = _texts()
    assert texts
    one = next(t for t in texts if 'D_B.value' in t and '((__repair_member_s32_4 *) cur)->value' in t and t.count('->value') == 1)
    assert 'typedef struct { char pad[4]; s32 value; } __repair_member_s32_4;' in one
    assert 'typedef struct { s32 value; } __repair_global_s32;' in one
    assert 'extern __repair_global_s32 D_B;' in one
    assert one.index('typedef struct { s32 value; } __repair_global_s32;') < one.index('extern __repair_global_s32 D_B;')
    assert 'count = D_B.value;' in one
    assert '*((s32 *) (((char *) tail) + 0)) = 1;' in one  # the other store is left raw in the single-store child


def test_every_use_of_the_global_in_the_function_is_the_member():
    one = next(t for t in _texts() if 'D_A.value' in t)
    assert 'D_A.value = D_A.value + 8;' in one
    assert 'extern s32 D_B;' in one


def test_a_volatile_global_or_one_used_outside_is_left_alone():
    assert not any('D_V.value' in t for t in _texts())
    other = SOURCE.replace('void draw', 'void other(void) { D_A = 0; }\nvoid draw')
    assert not any('D_A.value' in t for t in _texts(other))


def test_a_misaligned_offset_or_a_far_store_is_not_offered():
    odd = SOURCE.replace('+ 4)', '+ 3)')
    assert not any('__repair_member_s32_3' in t for t in _texts(odd))
    far = 'extern s32 D_B;\nvoid draw(void *cur)\n{\n  s32 count;\n  *((s32 *) (((char *) cur) + 4)) = 1;\n' + '  count = 1;\n' * 14 + '  count = D_B;\n}\n'
    assert m.variants(far, 'draw') == []


def test_a_function_without_raw_stores_has_nothing():
    assert m.variants('extern s32 D_A;\nvoid f(void)\n{\n  D_A = 1;\n}\n', 'f') == []


MEMBER_SOURCE = '''typedef union { struct { u32 w0; u32 w1; } words; long long pad; } Gfx;
extern s32 D_MODE;
extern s32 D_BORDER;
extern Gfx *D_CURSOR;
void draw(s32 arg0)
{
  Gfx *gp;
  s32 mode;
  gp = D_CURSOR;
  gp[0].words.w1 = 0xFFFCFFFC;
  gp[1].words.w0 = arg0;
  mode = D_MODE;
  if (D_BORDER)
  {
    func(mode);
  }
}
'''


def test_stores_that_are_members_already_offer_the_global_alone_as_a_record():
    # 1195 -> 390 on a 343-instruction display-list function: the read of the mode word could no longer be hoisted
    # above the member stores (exact-judge replay in decompdecomp's tests needs the compiler).
    texts = _texts(MEMBER_SOURCE)
    one = next(t for t in texts if 'mode = D_MODE.value;' in t)
    assert 'extern __repair_global_s32 D_MODE;' in one
    assert 'gp[0].words.w1 = 0xFFFCFFFC;' in one  # the stores are left as written
    assert '__repair_member_' not in one


def test_a_second_global_reuses_the_record_type_an_earlier_child_declared():
    first = next(t for t in _texts(MEMBER_SOURCE) if 'D_MODE.value' in t)
    both = [t for _, t in m.variants(first, 'draw') if 'D_BORDER.value' in t]
    assert both
    assert both[0].count('} __repair_global_s32;') == 1


def test_no_member_or_raw_store_means_no_variant():
    assert not _texts(MEMBER_SOURCE.replace('gp[0].words.w1 = 0xFFFCFFFC;', 'x = 1;').replace('gp[1].words.w0 = arg0;', 'y = 2;'))
