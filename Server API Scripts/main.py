from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
from jose import JWTError, jwt
from dotenv import load_dotenv
import os
from passlib.context import CryptContext
from models import Base, Transaction
from pydantic import BaseModel
from typing import List
from datetime import date
import csv
from io import StringIO
from models import Base, Transaction, UserModel

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI()

class User(BaseModel):
    username: str
    email: str
    is_active: bool

    class Config:
        from_attributes = True


class TransactionSchema(BaseModel):
    transaction_date: date
    description: str
    amount: float
    category: str
    card: str
    multiplier: float | None = None
    points: float | None = None

    class Config:
        from_attributes = True

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def authenticate_user(db: Session, username: str, password: str):
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> UserModel:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(UserModel).filter(UserModel.username == username).first()
    if user is None:
        raise credentials_exception
    return user

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username/password")
    token = create_access_token({"sub": user.username}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": token, "token_type": "bearer"}

@app.post("/transactions/", response_model=TransactionSchema)
def create_transaction(
    transaction: TransactionSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user)
):
    db_transaction = Transaction(**transaction.dict(), user_id=user.id)
    db.add(db_transaction)
    try:
        db.commit()
        db.refresh(db_transaction)
        return db_transaction
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Transaction already exists.")

@app.get("/transactions/", response_model=List[TransactionSchema])
def read_transactions(
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100
):
    return db.query(Transaction).filter_by(user_id=user.id)\
             .order_by(Transaction.transaction_date.desc())\
             .offset(skip).limit(limit).all()

@app.get("/me", response_model=User)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/transactions/summary/")
def get_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    total = db.query(func.sum(Transaction.amount)).scalar() or 0
    total_points = db.query(func.sum(Transaction.points)).scalar() or 0
    return {"total_spent": total, "total_points": total_points}

@app.get("/multipliers/")
def get_multipliers(db: Session = Depends(get_db), user: UserModel = Depends(get_current_user)):
    return db.query(Multiplier).all()


@app.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: UserModel = Depends(get_current_user),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    contents = await file.read()
    decoded = contents.decode("utf-8")
    csv_reader = csv.DictReader(StringIO(decoded))

    added = 0
    skipped = 0

    for row in csv_reader:
        try:
            tx_date = date.fromisoformat(row["transaction_date"])
            tx = Transaction(
                transaction_date=tx_date,
                description=row["description"].strip(),
                amount=float(row["amount"]),
                category=row["category"].strip(),
                card=row["card"].strip(),
                user_id=user.id
            )
            tx.calculate_points(db)



            # Check for duplicates
            exists = db.query(Transaction).filter_by(
                transaction_date=tx.transaction_date,
                description=tx.description,
                amount=tx.amount,
                card=tx.card,
            ).first()

            if exists:
                skipped += 1
                continue

            db.add(tx)
            added += 1

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Row parsing failed: {e}")

    db.commit()

    return {
        "status": "success",
        "added": added,
        "skipped": skipped,
        "filename": file.filename,
    }