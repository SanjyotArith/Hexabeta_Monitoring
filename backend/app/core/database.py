from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Scope connection session to use the 'hexa' schema by default
connect_args = {
    "server_settings": {
        "search_path": f"{settings.PGSCHEMA},public"
    }
}

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()
Base.metadata.schema = settings.PGSCHEMA

async def get_db():
    """Dependency injection yield for Database Sessions."""
    async with SessionLocal() as session:
        yield session
