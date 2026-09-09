import unittest
from regions import extract_regions, REGIONS

class RegionsTest(unittest.TestCase):
    def test_all_regions(self):
        for region in REGIONS:
            suffix = {'Hlavní město Praha':'hlavní město Prahu','Kraj Vysočina':'Vysočinu'}.get(region,region)
            for prefix in ('Katastrální úřad pro ', 'Katastrálním úřadem pro ', 'Katastrálního úřadu pro '):
                with self.subTest(region=region,prefix=prefix):
                    self.assertEqual(extract_regions(prefix+suffix)[0]['kraj'],region)
    def test_multiple_and_late(self):
        text='x '*31000+'Katastralni urad pro\nStredocesky kraj; Katastrální úřad pro Vysočinu'
        self.assertEqual({x['kraj'] for x in extract_regions(text)}, {'Středočeský kraj','Kraj Vysočina'})
    def test_unrelated_address(self):
        self.assertEqual(extract_regions('Dlužník Praha, správce Brno, Krajský soud v Praze'),[])
    def test_code_and_name(self):
        rows=[dict(ku_kod='601527',ku_nazev='Běchovice',kraj='Hlavní město Praha')]
        for text in ('k. ú. Běchovice', 'Katastrální území: 601527', 'k.ú. Běchovice [601527]'):
            self.assertEqual(extract_regions(text,rows)[0]['kraj'],'Hlavní město Praha')
        self.assertEqual(extract_regions('k.ú. Běchovice [999999]',rows),[])
    def test_ambiguity_and_boundaries(self):
        rows=[dict(ku_kod='111111',ku_nazev='Lhota',kraj='A'),dict(ku_kod='222222',ku_nazev='Lhota',kraj='B')]
        self.assertEqual(extract_regions('k.ú. Lhota',rows),[])
        self.assertEqual(extract_regions('k.ú. Lhotany',rows),[])
        self.assertEqual(extract_regions('k.ú. Lhota [222222]',rows)[0]['kraj'],'B')

if __name__=='__main__': unittest.main()
