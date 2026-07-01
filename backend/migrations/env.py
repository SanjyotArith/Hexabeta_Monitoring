import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the metadata target for autogenerate
target_metadata = Base.metadata

# Set database connection URL dynamically from settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def include_object(obj, name, type_, reflected, compare_to):
    """Ensure Alembic only inspects objects belonging to our target schema."""
    if type_ == "table":
        return obj.schema == settings.PGSCHEMA
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=settings.PGSCHEMA,
        include_schemas=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Set search path to target schema
        connection.execute(text(f"SET search_path TO {settings.PGSCHEMA}, public;"))
        connection.commit()
        
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=settings.PGSCHEMA,
            include_schemas=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
