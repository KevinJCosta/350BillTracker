"""Add user logins

Revision ID: 419caf2c892b
Revises: 65c13df197c5
Create Date: 2021-10-05 14:01:39.439376

"""
from alembic import op
import sqlalchemy as sa
import src


# revision identifiers, used by Alembic.
revision = '419caf2c892b'
down_revision = '65c13df197c5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('users',
    sa.Column('id', src.models.UUID(as_uuid=True), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('can_be_deleted', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.CheckConstraint('email = lower(email)', name='check_email_is_lowercase'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('login_links',
    sa.Column('user_id', src.models.UUID(as_uuid=True), nullable=False),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('expires_at', src.models.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('created_at', src.models.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('token')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('login_links')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    # ### end Alembic commands ###
