from sqlalchemy import Column,String,Text,BigInteger,DateTime, Boolean
from sqlalchemy.sql import func

from database import Base

class FileModel(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True)
    filename = Column(Text, nullable=False)
    path = Column(Text, nullable=False)
    size = Column(BigInteger, nullable=False)
    content_type = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    node_id = Column(String(50), nullable=False)
    replica_node_id = Column(String(50),nullable=False)
    deletion_pending = Column(Boolean, default=False, nullable=False)