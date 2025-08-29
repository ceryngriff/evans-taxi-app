"""Expand password columns to 255"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b6651b34c977"
down_revision = "fc04238e494b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("manager") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=100),
                       type_=sa.String(length=255),
                       existing_nullable=False)

    with op.batch_alter_table("driver") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=100),
                       type_=sa.String(length=255),
                       existing_nullable=False)

    with op.batch_alter_table("escort") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=100),
                       type_=sa.String(length=255),
                       existing_nullable=False)

    with op.batch_alter_table("mechanic") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=100),
                       type_=sa.String(length=255),
                       existing_nullable=False)


def downgrade():
    with op.batch_alter_table("manager") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=255),
                       type_=sa.String(length=100),
                       existing_nullable=False)
    with op.batch_alter_table("driver") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=255),
                       type_=sa.String(length=100),
                       existing_nullable=False)
    with op.batch_alter_table("escort") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=255),
                       type_=sa.String(length=100),
                       existing_nullable=False)
    with op.batch_alter_table("mechanic") as b:
        b.alter_column("password",
                       existing_type=sa.String(length=255),
                       type_=sa.String(length=100),
                       existing_nullable=False)
