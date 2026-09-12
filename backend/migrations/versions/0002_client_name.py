"""Enforce nonblank client names; invalid existing rows require manual correction."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Explicit Python Unicode whitespace set, independent of PostgreSQL locale.
    # Validation fails transactionally on invalid rows; no data is rewritten.
    op.create_check_constraint(
        op.f("ck_clients_nonblank_name"),
        "clients",
        "length(btrim(name, U&'"
        r"\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020"
        r"\0085\00A0\1680\2000\2001\2002\2003\2004\2005"
        r"\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000"
        "')) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_clients_nonblank_name"), "clients", type_="check")
