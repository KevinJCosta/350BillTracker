"""Remove old fields

Revision ID: 9fd6c4dbc2fe
Revises: 0a7676594ecb
Create Date: 2022-01-13 15:52:55.871137

"""
from alembic import op
import sqlalchemy as sa
import src


# revision identifiers, used by Alembic.
revision = '9fd6c4dbc2fe'
down_revision = '0a7676594ecb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('office_contacts',
    sa.Column('id', src.models.UUID(as_uuid=True), nullable=False),
    sa.Column('person_id', src.models.UUID(as_uuid=True), nullable=False),
    sa.Column('type', sa.Enum('CENTRAL_OFFICE', 'DISTRICT_OFFICE', 'OTHER', name='officecontacttype'), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('fax', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_office_contacts_person_id'), 'office_contacts', ['person_id'], unique=False)
    op.drop_column('council_members', 'legislative_phone')
    op.drop_column('persons', 'phone')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('persons', sa.Column('phone', sa.TEXT(), autoincrement=False, nullable=True))
    op.add_column('council_members', sa.Column('legislative_phone', sa.TEXT(), autoincrement=False, nullable=True))
    op.drop_index(op.f('ix_office_contacts_person_id'), table_name='office_contacts')
    op.drop_table('office_contacts')
    # ### end Alembic commands ###
