from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    InvalidBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
    parse_exact_decimal,
    validate_french_vat_number,
    validate_siren,
    validate_siret,
)

WORKSPACE_ID = UUID(int=1)
CLIENT_ID = UUID(int=2)
FRENCH_ADDRESS = BillingAddress(
    line1="10 rue de la Paix",
    line2="Bâtiment A",
    postal_code="75002",
    city="Paris",
    country_code="FR",
)


def workspace_profile(**changes: object) -> WorkspaceBillingProfile:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "legal_entity_kind": LegalEntityKind.COMPANY,
        "legal_name": "Exemple Conseil SAS",
        "trading_name": "Exemple",
        "siren": "552100554",
        "siret": "55210055400013",
        "vat_number": "FR96552100554",
        "legal_address": FRENCH_ADDRESS,
        "billing_address": None,
        "legal_form": "SAS",
        "share_capital": Decimal("1000.00"),
        "share_capital_currency": "EUR",
    }
    values.update(changes)
    return WorkspaceBillingProfile(**values)  # type: ignore[arg-type]


def test_workspace_company_profile_preserves_exact_legal_identity() -> None:
    profile = workspace_profile()
    assert profile.legal_name == "Exemple Conseil SAS"
    assert profile.trading_name == "Exemple"
    assert profile.share_capital == Decimal("1000.00")
    assert str(profile.share_capital) == "1000.00"
    assert profile.legal_address == FRENCH_ADDRESS


def test_individual_profile_excludes_company_only_fields() -> None:
    profile = workspace_profile(
        legal_entity_kind=LegalEntityKind.INDIVIDUAL,
        legal_name="Camille Martin EI",
        legal_form=None,
        share_capital=None,
        share_capital_currency=None,
    )
    assert profile.legal_entity_kind is LegalEntityKind.INDIVIDUAL
    with pytest.raises(InvalidBillingProfile, match="must not declare"):
        replace(profile, legal_form="EI")


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"legal_name": "\t\u00a0"}, "Legal name"),
        ({"legal_entity_kind": "company"}, "kind"),
        ({"legal_address": replace(FRENCH_ADDRESS, country_code="BE")}, "France-first"),
        ({"legal_form": None}, "legal form"),
        ({"share_capital": None}, "share capital"),
        ({"share_capital": Decimal("NaN")}, "finite"),
        ({"share_capital": Decimal("-0.01")}, "negative"),
        ({"share_capital": 1000.0}, "finite Decimal"),
        ({"share_capital_currency": "eur"}, "currency"),
    ],
)
def test_workspace_profile_rejects_invalid_fields(
    changes: dict[str, object], match: str
) -> None:
    with pytest.raises(InvalidBillingProfile, match=match):
        workspace_profile(**changes)


@pytest.mark.parametrize(
    "value",
    ["552100554", "356000000"],
)
def test_siren_checksum_validation(value: str) -> None:
    validate_siren(value)


@pytest.mark.parametrize(
    "value",
    ["", "55210055", "5521005540", "55210055A", "000000000", "552100555"],
)
def test_siren_rejects_malformed_or_bad_checksum(value: str) -> None:
    with pytest.raises(InvalidBillingProfile, match="SIREN"):
        validate_siren(value)


def test_siret_checksum_and_siren_ownership_validation() -> None:
    validate_siret("55210055400013", siren="552100554")
    validate_siret("35600000071472", siren="356000000")
    with pytest.raises(InvalidBillingProfile, match="start"):
        validate_siret("13002526500013", siren="552100554")
    with pytest.raises(InvalidBillingProfile, match="checksum"):
        validate_siret("55210055400014", siren="552100554")


def test_french_vat_numeric_key_and_profile_siren() -> None:
    validate_french_vat_number("FR96552100554", siren="552100554")
    validate_french_vat_number("FRAB552100554", siren="552100554")
    with pytest.raises(InvalidBillingProfile, match="key"):
        validate_french_vat_number("FR95552100554", siren="552100554")
    with pytest.raises(InvalidBillingProfile, match="profile SIREN"):
        validate_french_vat_number("FR83130025265", siren="552100554")


@pytest.mark.parametrize(
    "address",
    [
        BillingAddress("1 Main Street", "London", "GB", postal_code=None),
        BillingAddress("1 Main Street", "London", "GB", postal_code="SW1A 1AA"),
    ],
)
def test_structured_non_french_addresses_do_not_invent_postal_rules(
    address: BillingAddress,
) -> None:
    assert address.country_code == "GB"


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"line1": " "}, "line 1"),
        ({"line2": "\u2003"}, "line 2"),
        ({"city": ""}, "city"),
        ({"country_code": "fr"}, "Country code"),
        ({"country_code": "FRA"}, "Country code"),
        ({"postal_code": None}, "French address"),
        ({"postal_code": "7500A"}, "French address"),
    ],
)
def test_address_rejects_invalid_local_structure(
    changes: dict[str, object], match: str
) -> None:
    values: dict[str, object] = {
        "line1": FRENCH_ADDRESS.line1,
        "line2": FRENCH_ADDRESS.line2,
        "postal_code": FRENCH_ADDRESS.postal_code,
        "city": FRENCH_ADDRESS.city,
        "country_code": FRENCH_ADDRESS.country_code,
    }
    values.update(changes)
    with pytest.raises(InvalidBillingProfile, match=match):
        BillingAddress(**values)  # type: ignore[arg-type]


def test_client_legal_name_is_independent_from_display_name() -> None:
    profile = ClientBillingProfile(
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        legal_name="Acheteur Juridique SA",
        trading_name="Acheteur",
        siren="130025265",
        vat_number="FR07130025265",
        legal_address=BillingAddress(
            "20 avenue de France", "Paris", "FR", postal_code="75013"
        ),
    )
    assert profile.legal_name == "Acheteur Juridique SA"
    assert profile.trading_name == "Acheteur"


def test_french_client_requires_siren_and_vat_requires_siren() -> None:
    with pytest.raises(InvalidBillingProfile, match="requires a SIREN"):
        ClientBillingProfile(
            WORKSPACE_ID,
            CLIENT_ID,
            "French buyer",
            FRENCH_ADDRESS,
        )
    with pytest.raises(InvalidBillingProfile, match="requires the client's SIREN"):
        ClientBillingProfile(
            WORKSPACE_ID,
            CLIENT_ID,
            "Belgian buyer",
            BillingAddress("Rue de la Loi 1", "Bruxelles", "BE", postal_code="1000"),
            vat_number="FR96552100554",
        )


def test_exact_decimal_parser_never_accepts_float_or_nonfinite_values() -> None:
    assert parse_exact_decimal("1000.00100", field="Capital") == Decimal("1000.00100")
    for value in [1000.0, "NaN", "Infinity", "not-a-number"]:
        with pytest.raises(InvalidBillingProfile):
            parse_exact_decimal(value, field="Capital")  # type: ignore[arg-type]
