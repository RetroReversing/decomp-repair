"""A packed-word field compared with a counter gets the signed type a bit-field read has."""
import re

from decomprepair.field_extract_signed_cast import FAMILY, variants

CODE = '''extern unsigned char *gRec;
void run(unsigned int *word)
{
    unsigned int temp;
    int i;
    int j;
    temp = *word;
    for (i = 0; (i & 0xFFFF) < ((temp >> 0xC) & 0xF); i++) {
        for (j = 0; (j & 0xFFFF) < ((*word >> 8) & 0xF); j++) {
            gRec[j] = i;
        }
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_each_extract_beside_a_comparison_is_cast_alone_and_together():
    children = variants(CODE, 'run')
    assert {family for family, _ in children} == {FAMILY}
    texts = [squash(text) for _, text in children]
    assert len(texts) == 3
    assert any('< (s32) ((temp >> 0xC) & 0xF); i++' in text and '< ((*word >> 8) & 0xF)' in text for text in texts)
    assert any('< (s32) ((*word >> 8) & 0xF); j++' in text and '< ((temp >> 0xC) & 0xF)' in text for text in texts)
    assert any('(s32) ((temp >> 0xC) & 0xF)' in text and '(s32) ((*word >> 8) & 0xF)' in text for text in texts)


def test_other_uses_are_left_alone():
    assert variants(CODE.replace('(i & 0xFFFF) < ((temp >> 0xC) & 0xF)', '((temp >> 0xC) & 0xF) == i'), 'run')[0][1].count('(s32)') == 1
    plain = 'extern int G;\nvoid f(unsigned int w)\n{\n    G = (w >> 4) & 0xF;\n    G += ((w >> 4) & 0xFFFFF);\n}\n'
    assert variants(plain, 'f') == []
    assert variants(CODE.replace('(temp >> 0xC) & 0xF', '(temp >> n) & 0xF'), 'run')[0][1].count('(s32)') == 1
    assert variants(CODE, 'missing') == []
