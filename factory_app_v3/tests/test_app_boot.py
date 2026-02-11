def test_import_app_factory():
    from app.app import create_app

    app = create_app()
    assert app is not None


def test_attendance_not_registered():
    from app.app import create_app

    app = create_app()
    # ensure no attendance routes are present
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert not any(rule.startswith("/attendance") for rule in rules)
