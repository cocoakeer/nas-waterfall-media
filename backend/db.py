from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DB_PATH
import os

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MediaCache(Base):
    __tablename__ = "media_cache"
    rel_path = Column(String, primary_key=True)
    name = Column(String)
    type = Column(String)
    size = Column(Integer)
    mtime = Column(Float)
    cover_path = Column(String, nullable=True)
    cover_generated = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
