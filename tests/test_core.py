import copy
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from lmfit.lineshapes import gaussian, lorentzian, pvoigt, voigt
from xps_studio.core import (Spectrum, add_peak, fit_spectrum, load_file, export_result,
    save_parameters, read_parameters, background, make_model)
from xps_studio.plotting import load_export


class CoreTests(unittest.TestCase):
    def spectrum(self, kind='Gaussian'):
        x = np.linspace(280, 292, 400)
        funcs = {'Gaussian': gaussian, 'Lorentzian': lorentzian, 'Pseudo-Voigt': pvoigt, 'Voigt': voigt}
        y = funcs[kind](x, amplitude=1500, center=284.8, sigma=.5) + 100 + 2*x
        s = Spectrum('test.xlsx', 'C 1s', x, y)
        s.config['background'] = 'Linear'
        add_peak(s, kind)
        return s

    def test_model_recovery(self):
        for kind in ('Gaussian', 'Lorentzian', 'Pseudo-Voigt', 'Voigt'):
            with self.subTest(kind=kind):
                s = self.spectrum(kind); result = fit_spectrum(s)
                self.assertTrue(result['success'])
                self.assertAlmostEqual(result['params']['p1_center']['value'], 284.8, places=4)
                self.assertAlmostEqual(result['params']['p1_amplitude']['value'], 1500, places=2)
                np.testing.assert_allclose(result['total'], result['background'] + result['peaks']['p1_'])
                self.assertLess(np.max(np.abs(result['residual'])), .01)

    def test_constraints_and_progress(self):
        s = self.spectrum(); add_peak(s)
        s.config['params']['p2_center']['expr'] = 'p1_center + 1.5'
        s.config['params']['p1_sigma']['vary'] = False
        s.config['params']['p1_sigma']['value'] = .5
        progress = []
        result = fit_spectrum(s, progress.append)
        self.assertTrue(progress)
        self.assertAlmostEqual(result['params']['p2_center']['value'] - result['params']['p1_center']['value'], 1.5)
        self.assertEqual(result['params']['p1_sigma']['value'], .5)

    def test_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            df = pd.DataFrame({'Binding energy (eV)': [5, 4, 3, 2, 1, 1], 'Counts per second': [1, 2, 8, 3, 1, 3]})
            path = Path(folder) / 'facts.xlsx'
            with pd.ExcelWriter(path) as writer:
                for sheet in ['C 1s', 'Br 3d']: df.to_excel(writer, sheet_name=sheet, startrow=1, index=False)
                pd.DataFrame({'notes': ['not a spectrum']}).to_excel(writer, sheet_name='Notes', index=False)
            spectra, errors = load_file(path)
            self.assertEqual(len(spectra), 2); self.assertEqual(len(errors), 1)
            self.assertTrue(np.all(np.diff(spectra[0].x) > 0)); self.assertEqual(spectra[0].y[0], 2)
            csv = Path(folder) / 'facts.csv'
            csv.write_text('FACTS export\n' + df.to_csv(index=False), encoding='utf-8')
            self.assertEqual(len(load_file(csv)[0]), 1)
            csv.write_text(df.to_csv(index=False), encoding='utf-8')
            self.assertEqual(len(load_file(csv, skiprows=0)[0]), 1)
            dat = Path(folder) / 'simple.dat'; np.savetxt(dat, df.to_numpy())
            self.assertEqual(len(load_file(dat)[0]), 1)
            generic = Path(folder) / 'generic.csv'; df.to_csv(generic, header=False, index=False)
            self.assertEqual(len(load_file(generic, facts=False)[0]), 1)

    def test_roundtrip_export(self):
        with tempfile.TemporaryDirectory() as folder:
            s = self.spectrum(); s.result = fit_spectrum(s)
            for key in s.config['params']: s.config['params'][key] = s.result['params'][key]
            path = export_result(s, Path(folder) / 'fit.csv')
            loaded = load_export(path)
            np.testing.assert_allclose(loaded['total'], s.result['total'])
            np.testing.assert_allclose(loaded['peaks']['p1_'], s.result['peaks']['p1_'])
            summary = pd.read_csv(Path(folder) / 'fit_peaks.csv')
            self.assertAlmostEqual(summary.center_eV.iloc[0], 284.8, places=4)
            cfg = read_parameters(Path(folder) / 'fit_parameters.json')
            s.config = cfg
            self.assertTrue(fit_spectrum(s)['success'])

    def test_backgrounds_nonuniform_and_zero(self):
        s = self.spectrum()
        for kind in ('Shirley', 'Tougaard'):
            s.config['background'] = kind
            x = np.array([0., .1, .4, .8, 1., 2.])
            b = background(x, np.zeros(6), s.config)
            self.assertTrue(np.isfinite(b).all()); np.testing.assert_allclose(b, 0)
            b = background(x, np.ones(6) * 12, s.config)
            np.testing.assert_allclose(b, 12)
            r = fit_spectrum(s)
            self.assertTrue(np.isfinite(r['total']).all())
            np.testing.assert_allclose(r['total'], r['background'] + r['peaks']['p1_'])

    def test_cancel_and_invalid(self):
        with self.assertRaises(InterruptedError): fit_spectrum(self.spectrum(), cancelled=lambda: True)
        s = self.spectrum(); s.config['params']['p1_center']['min'] = 500
        with self.assertRaises(ValueError): make_model(s)
        s = self.spectrum(); s.config['region'] = [0, 1]
        with self.assertRaises(ValueError): fit_spectrum(s)


if __name__ == '__main__': unittest.main()
