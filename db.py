from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

DATABASE_URL = "sqlite:///./quizlic.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, nullable=False)
    generation_count = Column(Integer, default=0)

class QuizRequest(Base):
    __tablename__ = "quiz_requests"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    input_type = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    num_questions = Column(Integer, nullable=False)
    difficulty = Column(String, nullable=False)

    user = relationship("User", backref="quiz_requests")
    
if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Database and tables created.")