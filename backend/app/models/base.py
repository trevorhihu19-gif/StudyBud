import uuid
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

def gen_uuid() -> uuid.UUID:
    return uuid.uuid4()