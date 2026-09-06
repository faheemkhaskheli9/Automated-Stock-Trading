from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from modeling import targets
from modeling.tests.factories import ohlcv_frame

TZ = "Asia/Karachi"


def test_validate_and_task():
    assert targets.task_of({"type": "horizon_close", "horizon": 1}) == "regression"
    assert targets.task_of({"type": "direction", "horizon": 1}) == "classification"
    assert targets.is_multioutput({"type": "multistep", "steps": 4})
    with pytest.raises(ValueError):
        targets.validate_spec({"type": "bogus"})
    with pytest.raises(ValueError):
        targets.validate_spec({"type": "weekday_anchored", "entry_weekday": 4, "exit_weekday": 1})


def test_horizon_close_alignment():
    df = ohlcv_frame(60)
    idx = df.index[:55]
    y, tdates, avail, task = targets.build_target(
        {"type": "horizon_close", "horizon": 3}, df, decision_index=idx, exchange_tz=TZ
    )
    assert task == "regression"
    assert y.iloc[0] == pytest.approx(df["close"].iloc[3])
    assert tdates.iloc[0] == df.index[3].tz_convert(TZ).date()
    # available at next local midnight after the label bar
    expected = datetime.combine(tdates.iloc[0] + timedelta(days=1), time.min, ZoneInfo(TZ))
    assert avail.iloc[0] == pd.Timestamp(expected)


def test_horizon_return_and_direction():
    df = ohlcv_frame(40)
    idx = df.index[:35]
    yr, *_ = targets.build_target(
        {"type": "horizon_return", "horizon": 1}, df, decision_index=idx, exchange_tz=TZ
    )
    assert yr.iloc[0] == pytest.approx(df["close"].iloc[1] / df["close"].iloc[0] - 1)
    yd, _, _, task = targets.build_target(
        {"type": "direction", "horizon": 1}, df, decision_index=idx, exchange_tz=TZ
    )
    assert task == "classification"
    assert set(yd.dropna().unique()) <= {0.0, 1.0}


def test_multistep_matrix():
    df = ohlcv_frame(30)
    idx = df.index[:24]
    y, tdates, _, _ = targets.build_target(
        {"type": "multistep", "steps": 3}, df, decision_index=idx, exchange_tz=TZ
    )
    assert list(y.columns) == ["step_1", "step_2", "step_3"]
    assert y.iloc[0]["step_2"] == pytest.approx(df["close"].iloc[2])
    assert tdates.iloc[0] == df.index[3].tz_convert(TZ).date()


def test_weekday_anchored():
    df = ohlcv_frame(80)
    spec = {"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4}
    mondays = targets.decision_filter(spec, df.index, exchange_tz=TZ)
    assert len(mondays) > 5
    assert all(ts.tz_convert(TZ).weekday() == 0 for ts in mondays)

    y, tdates, _, _ = targets.build_target(spec, df, decision_index=mondays, exchange_tz=TZ)
    first_monday = mondays[0].tz_convert(TZ).date()
    friday = first_monday + timedelta(days=4)
    assert tdates.iloc[0] == friday
    assert y.iloc[0] == pytest.approx(
        float(df.loc[df.index.tz_convert(TZ).date == friday, "close"].iloc[0])
    )
    assert targets.derive_target_date(spec, first_monday) == friday


def test_derive_target_date_none_for_horizon():
    assert targets.derive_target_date({"type": "horizon_close", "horizon": 1}, None) is None
