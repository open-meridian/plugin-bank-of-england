"""The catalogue, from code, as the deployment approves it."""

from __future__ import annotations

from bank_of_england.declaration import DECLARATION


def test_three_datasets_rates_and_prices() -> None:
    assert [d.key for d in DECLARATION.catalogue] == ["boe_rates", "boe_curves", "boe_fx"]
    kinds = {d.key: list(d.data_types)[0] for d in DECLARATION.catalogue}
    assert kinds["boe_fx"] == "meridian.v1.Price" and kinds["boe_curves"] == "meridian.v1.Rate"
    for dataset in DECLARATION.catalogue:
        assert dataset.day_time_zone == "Europe/London" and dataset.vendor == "Bank of England"
        assert dataset.gap_recovery == "backfill" and not dataset.calendar_id
        said = dataset.terms_and_pricing
        assert "UK Open Government Licence" in said and "excessive use" in said
        assert len(said) <= 2000
    rates = DECLARATION.catalogue[0].terms_and_pricing
    assert "licensed under the Open Government Licence v3.0" in rates


def test_the_restricted_datasets_are_pulled_only_and_served_not_kept() -> None:
    modes = {d.key: list(d.modes) for d in DECLARATION.catalogue}
    # The catalogue holds each mode as its enum: push and pull for the rates.
    push, pull = modes["boe_rates"]
    assert push != pull and modes["boe_curves"] == modes["boe_fx"] == [pull]
    curves, fx = DECLARATION.catalogue[1:]
    for dataset in (curves, fx):
        assert "served, not kept" in dataset.terms_and_pricing
    assert "Bloomberg" in curves.terms_and_pricing and "Tradeweb" in curves.terms_and_pricing
    assert "excluded from the Open Government Licence" in fx.terms_and_pricing


def test_the_answers_are_kept_in_storage() -> None:
    assert DECLARATION.storage is not None
    assert [k.name for k in DECLARATION.storage.kinds] == ["responses"]
