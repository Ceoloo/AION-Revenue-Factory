import pytest

from aion_revenue_factory.outreach import TemplateError, render, required_variables, validate


def test_required_variables_ordered_unique():
    tpl = "Hi {{first_name}}, at {{company}} — {{first_name}}"
    assert required_variables(tpl) == ["first_name", "company"]


def test_render_substitutes():
    out = render("Hi {{first_name}} at {{company}}", {"first_name": "Dana", "company": "Voltify"})
    assert out == "Hi Dana at Voltify"


def test_whitespace_in_braces():
    assert render("{{ name }}", {"name": "X"}) == "X"


def test_missing_variable_fails():
    with pytest.raises(TemplateError):
        render("Hi {{first_name}} at {{company}}", {"first_name": "Dana"})


def test_empty_variable_treated_missing():
    with pytest.raises(TemplateError):
        validate("Hi {{company}}", {"company": ""})


def test_non_merge_braces_ignored():
    # single braces are not merge fields
    assert render("cost is {fixed}", {}) == "cost is {fixed}"
