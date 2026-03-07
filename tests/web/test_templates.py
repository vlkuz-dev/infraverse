import os

from jinja2 import Environment, FileSystemLoader


TEMPLATES_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "src",
    "infraverse",
    "web",
    "templates",
)


def _get_env():
    return Environment(loader=FileSystemLoader(TEMPLATES_DIR))


def test_base_template_exists():
    env = _get_env()
    template = env.get_template("base.html")
    assert template is not None


def test_base_template_renders():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render(active_page="dashboard")
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html


def test_base_template_has_tabler_css():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render()
    assert "tabler" in html
    assert "tabler.min.css" in html


def test_base_template_has_htmx():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render()
    assert "htmx.org" in html


def test_base_template_has_top_nav():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render()
    assert "Dashboard" in html
    assert "Comparison" in html
    assert "/comparison" in html


def test_base_template_dashboard_active():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render(active_page="dashboard")
    assert 'class="nav-item active"' in html


def test_base_template_comparison_active():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render(active_page="comparison")
    # The comparison nav-item should have active class
    # Find the comparison li element and verify it has the active class
    import re
    match = re.search(
        r'<li class="nav-item\s+active">\s*<a class="nav-link" href="/comparison">',
        html,
    )
    assert match is not None, "Comparison nav-item should have active class"


def test_base_template_custom_css():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render()
    assert "/static/style.css" in html


def test_base_template_version_footer():
    env = _get_env()
    template = env.get_template("base.html")
    html = template.render(version="99.88.77")
    assert "99.88.77" in html


def test_base_template_blocks():
    """Test that child templates can extend base.html."""
    env = _get_env()
    child_source = (
        '{% extends "base.html" %}'
        '{% block title %}Test Page{% endblock %}'
        '{% block page_title %}Test Title{% endblock %}'
        '{% block content %}<p>Hello</p>{% endblock %}'
    )
    child = env.from_string(child_source)
    html = child.render(active_page="dashboard")
    assert "<title>Test Page</title>" in html
    assert "Test Title" in html
    assert "<p>Hello</p>" in html


def test_static_css_exists():
    css_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "src",
        "infraverse",
        "web",
        "static",
        "style.css",
    )
    assert os.path.exists(css_path)
