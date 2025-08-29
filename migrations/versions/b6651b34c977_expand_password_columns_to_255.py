"""Expand password columns to 255

Revision ID: b6651b34c977
Revises: fc04238e494b
Create Date: 2025-08-29 10:11:34.705987

"""
def upgrade():
    # expand password column to 255 on all user tables
    for table in ("manager", "driver", "escort", "mechanic"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(
                "password",
                existing_type=sa.String(length=100),
                type_=sa.String(length=255),
                existing_nullable=False,
            )

def downgrade():
    # revert back to 100 if needed
    for table in ("manager", "driver", "escort", "mechanic"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(
                "password",
                existing_type=sa.String(length=255),
                type_=sa.String(length=100),
                existing_nullable=False,
            )

