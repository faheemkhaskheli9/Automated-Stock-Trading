from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from modeling.models import TradingModel
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db


@pytest.fixture
def rich_instrument():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=400)
    return inst


def test_rank_symbols_prints_a_table(rich_instrument):
    out = StringIO()
    call_command("train_weekday_models", "--rank-symbols", stdout=out)
    assert "ENGRO" in out.getvalue()


def test_rank_symbols_with_no_instruments_is_a_clean_noop():
    out = StringIO()
    call_command("train_weekday_models", "--rank-symbols", stdout=out)
    assert "No active instrument" in out.getvalue()


def test_trains_one_model_per_estimator_for_a_named_symbol(rich_instrument):
    out = StringIO()
    call_command(
        "train_weekday_models", "--symbol", "ENGRO", "--estimators", "ridge,drift", stdout=out
    )
    output = out.getvalue()
    assert "Trained 2 model(s) on ENGRO" in output
    assert "ridge" in output and "drift" in output
    assert TradingModel.objects.filter(estimator_key__in=["ridge", "drift"]).count() == 2


def test_unknown_symbol_raises_command_error(rich_instrument):
    with pytest.raises(CommandError):
        call_command("train_weekday_models", "--symbol", "NOPE", stdout=StringIO())


def test_auto_picks_symbol_when_none_given(rich_instrument):
    out = StringIO()
    call_command("train_weekday_models", "--estimators", "ridge", stdout=out)
    assert "Trained 1 model(s) on ENGRO" in out.getvalue()


def test_no_viable_instrument_warns_and_trains_nothing():
    make_instrument("THIN")
    out, err = StringIO(), StringIO()
    call_command("train_weekday_models", "--estimators", "ridge", stdout=out, stderr=err)
    assert "No models were trained" in out.getvalue()
    assert "No active instrument" in err.getvalue()
