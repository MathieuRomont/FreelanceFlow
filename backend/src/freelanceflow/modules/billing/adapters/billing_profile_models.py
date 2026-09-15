"""Relational rows for mutable legal billing profiles."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Numeric, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freelanceflow.shared.persistence import Base

_UNICODE_WHITESPACE = (
    "U&'"
    r"\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020"
    r"\0085\00A0\1680\2000\2001\2002\2003\2004\2005"
    r"\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000"
    "'"
)


def _nonblank(column: str) -> str:
    return f"length(btrim({column}, {_UNICODE_WHITESPACE})) > 0"


def _optional_nonblank(column: str) -> str:
    return f"({column} IS NULL OR {_nonblank(column)})"


def _address_constraints(prefix: str, *, required: bool) -> tuple[CheckConstraint, ...]:
    line1 = f"{prefix}_line1"
    line2 = f"{prefix}_line2"
    postal_code = f"{prefix}_postal_code"
    city = f"{prefix}_city"
    country_code = f"{prefix}_country_code"
    valid = (
        f"{_nonblank(line1)} AND {_optional_nonblank(line2)} AND {_nonblank(city)} "
        f"AND {country_code} ~ '^[A-Z]{{2}}$' "
        f"AND {_optional_nonblank(postal_code)} "
        f"AND ({country_code} <> 'FR' OR {postal_code} ~ '^[0-9]{{5}}$')"
    )
    expression = valid
    if not required:
        empty = (
            f"{line1} IS NULL AND {line2} IS NULL AND {postal_code} IS NULL "
            f"AND {city} IS NULL AND {country_code} IS NULL"
        )
        expression = f"({empty}) OR ({valid})"
    return (CheckConstraint(expression, name=f"valid_{prefix}_address"),)


class WorkspaceBillingProfileRow(Base):
    __tablename__ = "workspace_billing_profiles"
    __table_args__ = (
        CheckConstraint(
            "legal_entity_kind IN ('individual', 'company')",
            name="valid_legal_entity_kind",
        ),
        CheckConstraint(_nonblank("legal_name"), name="nonblank_legal_name"),
        CheckConstraint(_optional_nonblank("trading_name"), name="nonblank_trading_name"),
        CheckConstraint("siren ~ '^[0-9]{9}$'", name="siren_shape"),
        CheckConstraint("siret ~ '^[0-9]{14}$'", name="siret_shape"),
        CheckConstraint("left(siret, 9) = siren", name="siret_matches_siren"),
        CheckConstraint(
            "vat_number IS NULL OR "
            "(vat_number ~ '^FR[A-Z0-9]{2}[0-9]{9}$' "
            "AND right(vat_number, 9) = siren)",
            name="vat_number_shape",
        ),
        CheckConstraint("legal_country_code = 'FR'", name="french_legal_address"),
        CheckConstraint(
            "(legal_entity_kind = 'individual' AND legal_form IS NULL "
            "AND share_capital IS NULL AND share_capital_currency IS NULL) OR "
            "(legal_entity_kind = 'company' AND "
            f"{_nonblank('legal_form')} AND share_capital IS NOT NULL "
            "AND share_capital NOT IN ('NaN', 'Infinity', '-Infinity') "
            "AND share_capital >= 0 "
            "AND share_capital_currency ~ '^[A-Z]{3}$')",
            name="legal_form_and_capital",
        ),
        *_address_constraints("legal", required=True),
        *_address_constraints("billing", required=False),
    )

    workspace_id: Mapped[UUID] = mapped_column(primary_key=True)
    legal_entity_kind: Mapped[str]
    legal_name: Mapped[str]
    trading_name: Mapped[str | None]
    siren: Mapped[str]
    siret: Mapped[str]
    vat_number: Mapped[str | None]
    legal_form: Mapped[str | None]
    share_capital: Mapped[Decimal | None] = mapped_column(Numeric())
    share_capital_currency: Mapped[str | None]
    legal_line1: Mapped[str]
    legal_line2: Mapped[str | None]
    legal_postal_code: Mapped[str | None]
    legal_city: Mapped[str]
    legal_country_code: Mapped[str]
    billing_line1: Mapped[str | None]
    billing_line2: Mapped[str | None]
    billing_postal_code: Mapped[str | None]
    billing_city: Mapped[str | None]
    billing_country_code: Mapped[str | None]


class ClientBillingProfileRow(Base):
    __tablename__ = "client_billing_profiles"
    __table_args__ = (
        PrimaryKeyConstraint("client_id"),
        ForeignKeyConstraint(
            ["workspace_id", "client_id"],
            ["clients.workspace_id", "clients.id"],
        ),
        CheckConstraint(_nonblank("legal_name"), name="nonblank_legal_name"),
        CheckConstraint(_optional_nonblank("trading_name"), name="nonblank_trading_name"),
        CheckConstraint(
            "siren IS NULL OR siren ~ '^[0-9]{9}$'", name="siren_shape"
        ),
        CheckConstraint(
            "legal_country_code <> 'FR' OR siren IS NOT NULL",
            name="french_client_has_siren",
        ),
        CheckConstraint(
            "vat_number IS NULL OR "
            "(siren IS NOT NULL AND vat_number ~ '^FR[A-Z0-9]{2}[0-9]{9}$' "
            "AND right(vat_number, 9) = siren)",
            name="vat_number_shape",
        ),
        *_address_constraints("legal", required=True),
        *_address_constraints("billing", required=False),
    )

    client_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    legal_name: Mapped[str]
    trading_name: Mapped[str | None]
    siren: Mapped[str | None]
    vat_number: Mapped[str | None]
    legal_line1: Mapped[str]
    legal_line2: Mapped[str | None]
    legal_postal_code: Mapped[str | None]
    legal_city: Mapped[str]
    legal_country_code: Mapped[str]
    billing_line1: Mapped[str | None]
    billing_line2: Mapped[str | None]
    billing_postal_code: Mapped[str | None]
    billing_city: Mapped[str | None]
    billing_country_code: Mapped[str | None]
