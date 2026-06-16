"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa
revision='0001_initial'; down_revision=None; branch_labels=None; depends_on=None
def upgrade():
    from app.db.session import Base
    from app.models import entities  # noqa
    bind=op.get_bind(); Base.metadata.create_all(bind=bind)
def downgrade():
    from app.db.session import Base
    Base.metadata.drop_all(bind=op.get_bind())
