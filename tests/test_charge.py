import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
from lmfit.lineshapes import gaussian
from xps_studio.core import (Spectrum, add_peak, fit_spectrum, charge_reference,
    apply_charge_shift, make_model, save_parameters, read_parameters)


def reference_spectrum():
    x = np.linspace(280, 294, 400)
    s = Spectrum('reference.xlsx', 'Any sheet name', x,
                 gaussian(x, 1200, 286.3, .5) + 20 + 2 * (x - 280))
    s.config['background'] = 'Linear'
    add_peak(s, 'Gaussian')
    _, params = make_model(s)
    from xps_studio.core import parameter_dict
    for key in ('bkg_slope', 'bkg_intercept'):
        s.config['params'][key] = parameter_dict(params[key])
    s.result = fit_spectrum(s)
    for key in s.config['params']:
        s.config['params'][key] = copy.deepcopy(s.result['params'][key])
    s.result['config'] = copy.deepcopy(s.config)
    return s


class ChargeTests(unittest.TestCase):
    def test_explicit_reference_and_absolute_shift(self):
        s = reference_spectrum()
        self.assertEqual(s.config['shift'], 0.)
        original = copy.deepcopy(s.result)
        record = charge_reference(s, 'p1_', 284.8)
        self.assertAlmostEqual(record['shift_eV'], -1.5, places=5)
        self.assertEqual(record['sheet'], 'Any sheet name')
        self.assertIn('p1_center', record['fit_params'])
        apply_charge_shift(s, record['shift_eV'], record)
        self.assertAlmostEqual(s.result['params']['p1_center']['value'], 284.8, places=5)
        np.testing.assert_allclose(s.result['total'], original['total'])
        np.testing.assert_allclose(s.result['residual'], original['residual'])
        np.testing.assert_allclose(s.result['x'], original['x'] - 1.5, atol=1e-5)
        model, params = make_model(s)
        np.testing.assert_allclose(model.eval(params, x=s.result['x']), s.result['total'], atol=1e-6)
        first_region = list(s.config['region'])
        apply_charge_shift(s, record['shift_eV'], record)
        np.testing.assert_allclose(first_region, s.config['region'])
        # Re-recording an already corrected peak must retain the absolute shift.
        second = charge_reference(s, 'p1_', 284.8)
        self.assertAlmostEqual(second['shift_eV'], -1.5, places=5)
        replacement = charge_reference(s, 'p1_', 285.8)
        apply_charge_shift(s, replacement['shift_eV'], replacement)
        self.assertAlmostEqual(s.config['shift'], -.5, places=5)
        self.assertAlmostEqual(s.result['params']['p1_center']['value'], 285.8, places=5)
        apply_charge_shift(s, 0.)
        np.testing.assert_allclose(s.result['x'], original['x'])
        self.assertAlmostEqual(s.config['params']['p1_center']['value'], 286.3, places=5)

    def test_record_requires_success(self):
        s = reference_spectrum()
        s.result['success'] = False
        with self.assertRaises(ValueError): charge_reference(s, 'p1_', 284.8)
        s.result = None
        with self.assertRaises(ValueError): charge_reference(s, 'p1_', 284.8)

    def test_constraints_survive_translation(self):
        s = reference_spectrum()
        add_peak(s, 'Gaussian')
        s.config['params']['p2_center']['expr'] = 'p1_center + 1.2'
        s.config['params']['p2_amplitude']['expr'] = '(p1_center - 280) * 10'
        model, pars = make_model(s)
        x = s.x.copy(); original = model.eval(pars, x=x)
        apply_charge_shift(s, -1.5)
        model, shifted = make_model(s)
        self.assertAlmostEqual(shifted['p2_center'].value, pars['p2_center'].value - 1.5)
        self.assertAlmostEqual(shifted['p2_amplitude'].value, pars['p2_amplitude'].value)
        np.testing.assert_allclose(model.eval(shifted, x=x - 1.5), original, atol=1e-7)
        # A fixed literal expression is also a coordinate-dependent center.
        s.config['params']['p2_center']['expr'] = '286.0'
        apply_charge_shift(s, -.5)
        _, pars = make_model(s)
        self.assertAlmostEqual(pars['p2_center'].value, 287.)

    def test_record_saved_with_parameters(self):
        s = reference_spectrum(); record = charge_reference(s, 'p1_', 284.8)
        apply_charge_shift(s, record['shift_eV'], record)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'parameters.json'; save_parameters(s, path)
            loaded = read_parameters(path)
            self.assertEqual(loaded['charge_reference'], record)
            self.assertAlmostEqual(loaded['shift'], -1.5, places=5)


if __name__ == '__main__': unittest.main()
