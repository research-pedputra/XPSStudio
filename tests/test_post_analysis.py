import copy
import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from xps_studio.post_analysis import (record, quantify, doublets, identity, load_records,
                                     save_session, read_session, PRESETS)


def example(sample='sample.xlsx'):
    rows = []
    for element, ratio, centers in [('Cs', 1, (724.2, 738.0)), ('Pb', 1, (138., 143.251)), ('Br', 3, (68.669, 69.5))]:
        level, rsf, _ = PRESETS[element]
        for i, center in enumerate(centers):
            rows.append(record(sample, element+level, f'p{i+1}_', element+' '+level,
                               center, rsf*ratio*(2 if i == 0 else 1)*100,
                               'Fitted', 'fixture'))
    return rows


class PostAnalysisTests(unittest.TestCase):
    def test_example_and_sample_isolation(self):
        rows = example() + example('other.xlsx')
        results = quantify(rows)
        self.assertEqual(len(results), 6)
        for r in results:
            self.assertAlmostEqual(r['atomic_percent'], 60 if r['element'] == 'Br' else 20)
        self.assertAlmostEqual(sum(r['weight_percent'] for r in results[:3]), 100)
        rows[0]['included'] = False
        changed = quantify(rows)
        self.assertNotEqual(changed[0]['atomic_percent'], results[0]['atomic_percent'])
        self.assertEqual(changed[3:], results[3:])

    def test_doublet_and_validation(self):
        rows = example(); pairs = [{'a': identity(rows[2]), 'b': identity(rows[3])}]
        value = doublets(rows, pairs)[0]
        self.assertAlmostEqual(value['separation_eV'], 5.251)
        self.assertAlmostEqual(value['area_ratio_a_over_b'], 2)
        with self.assertRaises(ValueError): doublets(rows, [{'a': identity(rows[0]), 'b': identity(rows[3])}])
        for bad in (0, -1, 'nan', 'abc'):
            candidate = copy.deepcopy(rows); candidate[0]['rsf'] = bad
            with self.assertRaises(ValueError): quantify(candidate)
        candidate = copy.deepcopy(rows); candidate[0]['area_full'] = -1
        with self.assertRaises(ValueError): quantify(candidate)
        for row in rows: row['atomic_weight'] = ''
        self.assertTrue(all(r['weight_percent'] is None for r in quantify(rows)))

    def test_load_legacy_and_summary_and_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); rows = example()
            summary = root/'result_peaks.csv'
            pd.DataFrame([dict(source=r['source'], sheet=r['sheet'], peak=r['peak'], label=r['label'],
                area_full=r['area_full'], center_eV=r['center_eV'], fit_success=True) for r in rows]).to_csv(summary, index=False)
            loaded = load_records(summary)
            self.assertEqual(quantify(loaded), quantify(rows))
            config = {'peaks': [{'prefix':'p1_', 'label':'Cs 3d', 'kind':'Voigt'}],
                      'params': {'p1_center': {'value':724.2}, 'p1_amplitude': {'value':10000}}}
            params = root/'old.json'; params.write_text(json.dumps({'schema':'xps-studio-1','config':config}))
            old = load_records(params)
            self.assertFalse(old[0]['included']); self.assertEqual(old[0]['status'], 'Unverified parameters')
            pairs = [{'a': list(identity(rows[0])), 'b': list(identity(rows[1]))}]
            session = root/'analysis.xpspost'; save_session(session, rows, pairs)
            self.assertEqual(read_session(session), (rows, pairs))
            raw = root/'alone.csv'; pd.DataFrame({'binding_energy_eV':[1,2]}).to_csv(raw,index=False)
            with self.assertRaisesRegex(ValueError, 'Full fitted areas'): load_records(raw)


if __name__ == '__main__': unittest.main()
