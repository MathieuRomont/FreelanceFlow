"""Mutable France-first billing identity configuration.

These values are current configuration, not invoice history. Invoice issuance must
copy the values it uses into an immutable invoice snapshot.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import StrEnum
from uuid import UUID


class InvalidBillingProfile(ValueError):
    """A billing profile is incomplete or locally invalid."""


class LegalEntityKind(StrEnum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$", re.ASCII)
_FRENCH_POSTAL_CODE = re.compile(r"^[0-9]{5}$", re.ASCII)
_SIREN = re.compile(r"^[0-9]{9}$", re.ASCII)
_SIRET = re.compile(r"^[0-9]{14}$", re.ASCII)
_FRENCH_VAT = re.compile(r"^FR([A-Z0-9]{2})([0-9]{9})$", re.ASCII)
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$", re.ASCII)


def _require_nonblank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidBillingProfile(f"{field} must not be blank")


def _validate_optional_text(value: str | None, field: str) -> None:
    if value is not None:
        _require_nonblank(value, field)


def _passes_luhn(value: str) -> bool:
    total = 0
    for index, character in enumerate(value):
        digit = int(character)
        if index % 2 == len(value) % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_siren(value: str) -> None:
    """Validate only the local shape and checksum, never registry existence."""
    if not isinstance(value, str) or not _SIREN.fullmatch(value):
        raise InvalidBillingProfile("SIREN must contain exactly 9 ASCII digits")
    if value == "000000000" or not _passes_luhn(value):
        raise InvalidBillingProfile("SIREN checksum is invalid")


def validate_siret(value: str, *, siren: str) -> None:
    """Validate SIRET shape, SIREN ownership, and the documented local checksum.

    La Poste establishment identifiers use the official digit-sum exception.
    Neither route verifies registration against SIRENE.
    """
    if not isinstance(value, str) or not _SIRET.fullmatch(value):
        raise InvalidBillingProfile("SIRET must contain exactly 14 ASCII digits")
    if value[:9] != siren:
        raise InvalidBillingProfile("SIRET must start with the profile SIREN")
    valid_checksum = (
        sum(int(character) for character in value) % 5 == 0
        if siren == "356000000"
        else _passes_luhn(value)
    )
    if not valid_checksum:
        raise InvalidBillingProfile("SIRET checksum is invalid")


def validate_french_vat_number(value: str, *, siren: str) -> None:
    """Validate French VAT structure and the numeric-key formula when applicable."""
    if not isinstance(value, str):
        raise InvalidBillingProfile("French VAT number must be a string")
    match = _FRENCH_VAT.fullmatch(value)
    if match is None:
        raise InvalidBillingProfile(
            "French VAT number must be FR, a two-character key, and a 9-digit SIREN"
        )
    key, vat_siren = match.groups()
    if vat_siren != siren:
        raise InvalidBillingProfile("French VAT number must contain the profile SIREN")
    if key.isdigit():
        expected = (12 + 3 * (int(siren) % 97)) % 97
        if key != f"{expected:02d}":
            raise InvalidBillingProfile("French VAT number key is invalid")


def parse_exact_decimal(value: str | None, *, field: str) -> Decimal | None:
    """Parse exact decimal text without accepting or passing through float."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidBillingProfile(f"{field} must be exact decimal text")
    try:
        parsed = Decimal(value)
    except DecimalException as error:
        raise InvalidBillingProfile(f"{field} must be exact decimal text") from error
    if not parsed.is_finite():
        raise InvalidBillingProfile(f"{field} must be finite")
    return parsed


@dataclass(frozen=True)
class BillingAddress:
    line1: str
    city: str
    country_code: str
    postal_code: str | None = None
    line2: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.line1, "Address line 1")
        _require_nonblank(self.city, "Address city")
        _validate_optional_text(self.line2, "Address line 2")
        if not isinstance(self.country_code, str) or not _COUNTRY_CODE.fullmatch(
            self.country_code
        ):
            raise InvalidBillingProfile(
                "Country code must contain exactly 2 uppercase ASCII letters"
            )
        _validate_optional_text(self.postal_code, "Postal code")
        if self.country_code == "FR" and (
            self.postal_code is None
            or _FRENCH_POSTAL_CODE.fullmatch(self.postal_code) is None
        ):
            raise InvalidBillingProfile(
                "A French address requires a 5-digit postal code"
            )


@dataclass(frozen=True)
class WorkspaceBillingProfile:
    workspace_id: UUID
    legal_entity_kind: LegalEntityKind
    legal_name: str
    siren: str
    siret: str
    legal_address: BillingAddress
    trading_name: str | None = None
    billing_address: BillingAddress | None = None
    vat_number: str | None = None
    legal_form: str | None = None
    share_capital: Decimal | None = None
    share_capital_currency: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, UUID):
            raise InvalidBillingProfile("Workspace ID must be a UUID")
        if not isinstance(self.legal_entity_kind, LegalEntityKind):
            raise InvalidBillingProfile("Legal entity kind is invalid")
        _require_nonblank(self.legal_name, "Legal name")
        _validate_optional_text(self.trading_name, "Trading name")
        if self.legal_address.country_code != "FR":
            raise InvalidBillingProfile(
                "The France-first seller profile requires a French legal address"
            )
        validate_siren(self.siren)
        validate_siret(self.siret, siren=self.siren)
        if self.vat_number is not None:
            validate_french_vat_number(self.vat_number, siren=self.siren)

        if self.legal_entity_kind is LegalEntityKind.INDIVIDUAL:
            if any(
                value is not None
                for value in (
                    self.legal_form,
                    self.share_capital,
                    self.share_capital_currency,
                )
            ):
                raise InvalidBillingProfile(
                    "Individual sellers must not declare company legal form or capital"
                )
            return

        _validate_optional_text(self.legal_form, "Company legal form")
        if self.legal_form is None:
            raise InvalidBillingProfile("Company legal form is required")
        if not isinstance(self.share_capital, Decimal) or not self.share_capital.is_finite():
            raise InvalidBillingProfile("Company share capital must be a finite Decimal")
        if self.share_capital < 0:
            raise InvalidBillingProfile("Company share capital must not be negative")
        if (
            not isinstance(self.share_capital_currency, str)
            or _CURRENCY_CODE.fullmatch(self.share_capital_currency) is None
        ):
            raise InvalidBillingProfile(
                "Company share capital currency must be 3 uppercase ASCII letters"
            )


@dataclass(frozen=True)
class ClientBillingProfile:
    workspace_id: UUID
    client_id: UUID
    legal_name: str
    legal_address: BillingAddress
    trading_name: str | None = None
    billing_address: BillingAddress | None = None
    siren: str | None = None
    vat_number: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, UUID) or not isinstance(self.client_id, UUID):
            raise InvalidBillingProfile("Workspace and client IDs must be UUIDs")
        _require_nonblank(self.legal_name, "Legal name")
        _validate_optional_text(self.trading_name, "Trading name")
        if self.legal_address.country_code == "FR" and self.siren is None:
            raise InvalidBillingProfile("A French client legal address requires a SIREN")
        if self.siren is not None:
            validate_siren(self.siren)
        if self.vat_number is not None:
            if self.siren is None:
                raise InvalidBillingProfile(
                    "A French VAT number requires the client's SIREN"
                )
            validate_french_vat_number(self.vat_number, siren=self.siren)
