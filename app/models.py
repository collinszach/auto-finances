from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Numeric,
    Boolean,
    ForeignKey,
    Text,
    UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base
from math import floor
import re

Base = declarative_base()

# --------------------------
# User model
# --------------------------
class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    transactions = relationship("Transaction", back_populates="user")

# --------------------------
# Transaction model
# --------------------------
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_date = Column(Date, nullable=False, index=True)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    category = Column(Text, nullable=True)
    card = Column(Text, nullable=False)
    multiplier_id = Column(Integer, ForeignKey("multipliers.id"), nullable=True)
    points = Column(Numeric(10, 2), nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("UserModel", back_populates="transactions")
    multiplier = relationship("Multiplier")

    def calculate_points(self, db_session=None):
        desc = self.description.upper()
        if re.search(r'\bAUTO\b', desc) and re.search(r'\bPAY\b', desc):
            self.points = None
            return

        if db_session and self.category and self.card:
            self.multiplier = db_session.query(Multiplier).filter_by(
                category=self.category,
                card=self.card
            ).first()
            if not self.multiplier:
                self.points = None
                return

        if self.amount is not None and self.multiplier and self.multiplier.multiplier:
            self.points = round(float(self.amount)) * self.multiplier.multiplier

# --------------------------
# Multiplier model
# --------------------------
class Multiplier(Base):
    __tablename__ = "multipliers"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)
    card = Column(String, nullable=False)
    multiplier = Column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("category", "card", name="uq_category_card"),)
