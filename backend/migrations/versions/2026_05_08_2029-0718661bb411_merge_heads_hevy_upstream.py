"""merge heads (hevy + upstream)

Revision ID: 0718661bb411
Revises: a1b2c3d4e5f7, d15dee848b33

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0718661bb411'
down_revision: Union[str, None] = ('a1b2c3d4e5f7', 'd15dee848b33')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
