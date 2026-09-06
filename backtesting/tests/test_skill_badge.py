"""Unit tests for the shared ``skill_badges`` template library used by the
``backtesting`` and ``forecasting`` walk-forward runner pages."""

from django.template import Context, Template

from backtesting.templatetags.skill_badges import skill_badge, skill_state


def _render(snippet, **ctx):
    return Template("{% load skill_badges %}" + snippet).render(Context(ctx))


class TestSkillState:
    def test_positive_is_good(self):
        assert skill_state(0.12) == "good"

    def test_zero_is_bad(self):
        assert skill_state(0.0) == "bad"

    def test_negative_is_bad(self):
        assert skill_state(-0.4) == "bad"

    def test_missing_is_none(self):
        assert skill_state(None) == "none"

    def test_non_numeric_is_none(self):
        assert skill_state("n/a") == "none"


class TestSkillBadge:
    def test_positive_renders_good_pill_with_3dp(self):
        out = skill_badge(0.1234)
        assert 'class="skill-badge good"' in out
        assert ">0.123<" in out

    def test_negative_renders_bad_pill(self):
        out = skill_badge(-0.05)
        assert 'class="skill-badge bad"' in out
        assert ">-0.050<" in out

    def test_missing_renders_dash_pill(self):
        out = skill_badge(None)
        assert 'class="skill-badge none"' in out
        assert "—" in out

    def test_leaky_overrides_colour_and_adds_title(self):
        out = skill_badge(0.999, leaky=True)
        assert 'class="skill-badge leaky"' in out
        assert "leakage" in out

    def test_leaky_ignored_when_no_score(self):
        out = skill_badge(None, leaky=True)
        assert 'class="skill-badge none"' in out

    def test_output_is_html_safe(self):
        # format_html escapes; the badge is marked safe so the pill renders.
        out = skill_badge(0.5)
        assert "&lt;" not in out and "<span" in out


class TestInTemplate:
    def test_tag_loads_and_renders_in_a_template(self):
        html = _render("{% skill_badge value %}", value=0.42)
        assert 'class="skill-badge good"' in html
        assert "0.420" in html

    def test_leaky_kwarg_from_template(self):
        html = _render("{% skill_badge value leaky=flag %}", value=0.97, flag=True)
        assert 'class="skill-badge leaky"' in html

    def test_filter_form(self):
        html = _render("{{ value|skill_state }}", value=-1.0)
        assert html == "bad"
