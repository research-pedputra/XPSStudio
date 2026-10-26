"""Exercise the bundled GUI, solver, spreadsheet engine and project persistence."""
import json
import os
import tempfile
import time
from pathlib import Path


def run(report):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import pandas as pd
    import xlrd
    from PySide6.QtWidgets import QApplication
    from xps_studio.app import MainWindow, configure_app
    from xps_studio.core import export_result
    from xps_studio.matrix import MatrixDialog
    from xps_studio.plotting import load_export
    from xps_studio.post_dialog import PostAnalysisDialog
    from xps_studio.post_analysis import load_records, save_session, read_session
    from xps_studio.version import VERSION
    app = QApplication([]); configure_app(app)
    window = MainWindow(); window.show(); window.open_demo(); app.processEvents()
    window.start_fit()
    deadline = time.monotonic() + 90
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert window.worker is None, 'Fit timed out'
    result = window.current.result
    assert result is not None and result['success'], 'Fit failed'
    center = result['params']['p1_center']['value']
    assert abs(center - 284.8) < .05, center
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        csv = export_result(window.current, root/'spectrum.csv')
        frame = pd.read_csv(csv)
        frame.to_excel(root/'test.xlsx', index=False)
        assert len(pd.read_excel(root/'test.xlsx')) == len(frame)
        plot = MatrixDialog(); plot.append_dataset(str(csv), load_export(csv))
        plot.save_project_to(root/'test.xpsplot')
        restored = MatrixDialog(); restored.open_project_from(root/'test.xpsplot')
        assert len(restored.datasets) == 1
        figure = restored.build_figure(6, 4, 80)[0]
        for extension in ('png', 'pdf', 'svg'):
            figure.savefig(root/('plot.' + extension))
            assert (root/('plot.' + extension)).stat().st_size > 1000
        restored.peak_positions_frame().to_csv(root/'positions.csv', index=False)
        assert len(restored.peak_positions_frame()) == 2
        post = PostAnalysisDialog(window); post.load_paths([csv])
        assert len(post.records) == 2 and len(post.pairs) == 1
        parameters = load_records(root/'spectrum_parameters.json')
        assert len(parameters) == 2 and parameters[0]['status'] == 'Fitted'
        assert len(load_records(root/'test.xpsplot')) == 2
        for row in post.records: row.update(element='C', transition='1s', rsf=1, atomic_weight=12)
        post.refresh(); assert not post.last_error, post.last_error
        post.export_to(root/'composition.csv')
        assert abs(pd.read_csv(root/'composition.csv').atomic_percent.iloc[0] - 100) < 1e-8
        save_session(root/'analysis.xpspost', post.records, post.pairs)
        assert read_session(root/'analysis.xpspost')[0] == post.records
        post.close()
        plot.close(); restored.close()
    window.close(); app.processEvents()
    report.write_text(json.dumps({'success': True, 'version': VERSION, 'center_eV': center,
        'checks': ['Qt startup', 'threaded fitting', 'CSV export', 'Excel round-trip',
                   'project save/reopen', 'PNG/PDF/SVG export', 'peak positions',
                   'post-analysis import, quantification, doublets, sessions and CSV export']}, indent=2), encoding='utf-8')
