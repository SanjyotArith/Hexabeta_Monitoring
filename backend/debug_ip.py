import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
from app.models.infrastructure import Machine
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(Machine).limit(1))
        machine = result.scalars().first()
        if machine:
            print(f"Machine found! IP: {machine.ip_address}")
        else:
            print("No machine found in DB")

asyncio.run(main())
