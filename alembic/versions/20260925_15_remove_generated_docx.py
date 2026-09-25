"""Remove files created by the retired internal DOCX generator.

Documents now arrive from AIS, so generated_docx is no longer a supported
attachment kind. Historical audit rows remain immutable, but the generated
binary attachments themselves are deliberately removed.
"""

import sqlalchemy as sa
from alembic import op


revision = "20260925_15"
down_revision = "20260924_14"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        "DELETE FROM document_attachment WHERE file_kind = 'generated_docx'"
    ))


def downgrade():
    raise NotImplementedError("Deleted generated files cannot be reconstructed.")
