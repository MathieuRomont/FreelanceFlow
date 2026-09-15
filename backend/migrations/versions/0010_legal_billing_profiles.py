"""Add mutable France-first workspace and client legal billing profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

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


def _address_check(prefix: str, *, required: bool) -> str:
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
    if required:
        return valid
    empty = (
        f"{line1} IS NULL AND {line2} IS NULL AND {postal_code} IS NULL "
        f"AND {city} IS NULL AND {country_code} IS NULL"
    )
    return f"({empty}) OR ({valid})"


def _address_columns(prefix: str, *, required: bool) -> list[sa.Column[object]]:
    return [
        sa.Column(f"{prefix}_line1", sa.String(), nullable=not required),
        sa.Column(f"{prefix}_line2", sa.String(), nullable=True),
        sa.Column(f"{prefix}_postal_code", sa.String(), nullable=True),
        sa.Column(f"{prefix}_city", sa.String(), nullable=not required),
        sa.Column(f"{prefix}_country_code", sa.String(), nullable=not required),
    ]


def upgrade() -> None:
    op.create_table(
        "workspace_billing_profiles",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("legal_entity_kind", sa.String(), nullable=False),
        sa.Column("legal_name", sa.String(), nullable=False),
        sa.Column("trading_name", sa.String(), nullable=True),
        sa.Column("siren", sa.String(), nullable=False),
        sa.Column("siret", sa.String(), nullable=False),
        sa.Column("vat_number", sa.String(), nullable=True),
        sa.Column("legal_form", sa.String(), nullable=True),
        sa.Column("share_capital", sa.Numeric(), nullable=True),
        sa.Column("share_capital_currency", sa.String(), nullable=True),
        *_address_columns("legal", required=True),
        *_address_columns("billing", required=False),
        sa.CheckConstraint(
            "legal_entity_kind IN ('individual', 'company')",
            name=op.f("ck_workspace_billing_profiles_valid_legal_entity_kind"),
        ),
        sa.CheckConstraint(
            _nonblank("legal_name"),
            name=op.f("ck_workspace_billing_profiles_nonblank_legal_name"),
        ),
        sa.CheckConstraint(
            _optional_nonblank("trading_name"),
            name=op.f("ck_workspace_billing_profiles_nonblank_trading_name"),
        ),
        sa.CheckConstraint(
            "siren ~ '^[0-9]{9}$'",
            name=op.f("ck_workspace_billing_profiles_siren_shape"),
        ),
        sa.CheckConstraint(
            "siret ~ '^[0-9]{14}$'",
            name=op.f("ck_workspace_billing_profiles_siret_shape"),
        ),
        sa.CheckConstraint(
            "left(siret, 9) = siren",
            name=op.f("ck_workspace_billing_profiles_siret_matches_siren"),
        ),
        sa.CheckConstraint(
            "vat_number IS NULL OR "
            "(vat_number ~ '^FR[A-Z0-9]{2}[0-9]{9}$' "
            "AND right(vat_number, 9) = siren)",
            name=op.f("ck_workspace_billing_profiles_vat_number_shape"),
        ),
        sa.CheckConstraint(
            "legal_country_code = 'FR'",
            name=op.f("ck_workspace_billing_profiles_french_legal_address"),
        ),
        sa.CheckConstraint(
            "(legal_entity_kind = 'individual' AND legal_form IS NULL "
            "AND share_capital IS NULL AND share_capital_currency IS NULL) OR "
            "(legal_entity_kind = 'company' AND "
            f"{_nonblank('legal_form')} AND share_capital IS NOT NULL "
            "AND share_capital NOT IN ('NaN', 'Infinity', '-Infinity') "
            "AND share_capital >= 0 "
            "AND share_capital_currency ~ '^[A-Z]{3}$')",
            name=op.f("ck_workspace_billing_profiles_legal_form_and_capital"),
        ),
        sa.CheckConstraint(
            _address_check("legal", required=True),
            name=op.f("ck_workspace_billing_profiles_valid_legal_address"),
        ),
        sa.CheckConstraint(
            _address_check("billing", required=False),
            name=op.f("ck_workspace_billing_profiles_valid_billing_address"),
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", name=op.f("pk_workspace_billing_profiles")
        ),
    )
    op.create_table(
        "client_billing_profiles",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(), nullable=False),
        sa.Column("trading_name", sa.String(), nullable=True),
        sa.Column("siren", sa.String(), nullable=True),
        sa.Column("vat_number", sa.String(), nullable=True),
        *_address_columns("legal", required=True),
        *_address_columns("billing", required=False),
        sa.CheckConstraint(
            _nonblank("legal_name"),
            name=op.f("ck_client_billing_profiles_nonblank_legal_name"),
        ),
        sa.CheckConstraint(
            _optional_nonblank("trading_name"),
            name=op.f("ck_client_billing_profiles_nonblank_trading_name"),
        ),
        sa.CheckConstraint(
            "siren IS NULL OR siren ~ '^[0-9]{9}$'",
            name=op.f("ck_client_billing_profiles_siren_shape"),
        ),
        sa.CheckConstraint(
            "legal_country_code <> 'FR' OR siren IS NOT NULL",
            name=op.f("ck_client_billing_profiles_french_client_has_siren"),
        ),
        sa.CheckConstraint(
            "vat_number IS NULL OR "
            "(siren IS NOT NULL AND vat_number ~ '^FR[A-Z0-9]{2}[0-9]{9}$' "
            "AND right(vat_number, 9) = siren)",
            name=op.f("ck_client_billing_profiles_vat_number_shape"),
        ),
        sa.CheckConstraint(
            _address_check("legal", required=True),
            name=op.f("ck_client_billing_profiles_valid_legal_address"),
        ),
        sa.CheckConstraint(
            _address_check("billing", required=False),
            name=op.f("ck_client_billing_profiles_valid_billing_address"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "client_id"],
            ["clients.workspace_id", "clients.id"],
            name=op.f("fk_client_billing_profiles_workspace_id_clients"),
        ),
        sa.PrimaryKeyConstraint(
            "client_id", name=op.f("pk_client_billing_profiles")
        ),
    )


def downgrade() -> None:
    op.drop_table("client_billing_profiles")
    op.drop_table("workspace_billing_profiles")
