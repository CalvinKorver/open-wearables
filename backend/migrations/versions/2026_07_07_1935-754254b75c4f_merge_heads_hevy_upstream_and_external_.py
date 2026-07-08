"""merge_heads_hevy_upstream_and_external_provider_index

Revision ID: 754254b75c4f
Revises: 0718661bb411, 5aaff4551af6

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "754254b75c4f"
down_revision: Union[str, None] = ("0718661bb411", "5aaff4551af6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
