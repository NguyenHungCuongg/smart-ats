import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

# Migrations run as ats_owner, which owns every table; the app never gets these credentials
# (ADR-0001).
if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

with create_engine(os.environ["DATABASE_MIGRATION_URL"]).connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
