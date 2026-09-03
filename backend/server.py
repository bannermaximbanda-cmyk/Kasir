from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

class ProductInput(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    category: str = "Lain-lain"
    vendor: str = "MJD Kupi"
    price: float = 0
    cost: float = 0
    stock: int = 0

class StockAdjustment(BaseModel):
    quantity: int
    reason: str = "Restock"

class ExpenseInput(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str
    note: str = ""
    amount: float
    date: str
    method: str = "Cash"

class SaleLine(BaseModel):
    product_id: str
    name: str
    quantity: int
    price: float
    vendor: str = "MJD Kupi"

class SaleInput(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    table: str = "Meja 01"
    lines: List[SaleLine]
    subtotal: float
    tax: float = 0
    total: float
    payment_method: str = "Cash"

class LoginInput(BaseModel):
    email: str
    password: str

class SelfOrderInput(BaseModel):
    table: str
    lines: List[SaleLine]
    total: float
    notes: str = ""

class OutletInput(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    address: str = ""
    active: bool = True

class QrisInput(BaseModel):
    outlet_id: str
    qris_code: str
    logo_data: Optional[str] = None

ROLES = ["Super Admin", "Merchant Admin", "Vendor", "Kasir"]
DEMO_USERS = [
    ("superadmin@mjd-kupi.local", "MjdKupi#2026", "Super Admin", "Raka Owner"),
    ("manager@mjd-kupi.local", "MjdKupi#2026", "Merchant Admin", "Maya Ardianti"),
    ("vendor@mjd-kupi.local", "MjdKupi#2026", "Vendor", "Agus Tenant"),
    ("kasir@mjd-kupi.local", "MjdKupi#2026", "Kasir", "Dina Kasir"),
]

def public_user(doc):
    return {"id": doc["id"], "email": doc["email"], "role": doc["role"], "name": doc["name"], "outlet_id": doc.get("outlet_id", "outlet-sudirman")}

def token_for(user, token_type="access"):
    duration = timedelta(days=7) if token_type == "refresh" else timedelta(minutes=30)
    return jwt.encode({"sub": user["id"], "type": token_type, "exp": datetime.now(timezone.utc) + duration}, os.environ["JWT_SECRET"], algorithm="HS256")

async def current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token and request.headers.get("Authorization", "").startswith("Bearer "):
        token = request.headers["Authorization"][7:]
    if not token:
        raise HTTPException(status_code=401, detail="Login diperlukan")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="Sesi tidak valid")
        return user
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sesi kedaluwarsa") from exc

def require_roles(*roles):
    async def dependency(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Role tidak memiliki akses")
        return user
    return dependency

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

@api_router.get("/products", response_model=List[ProductInput])
async def list_products():
    return await db.products.find({}, {"_id": 0}).to_list(1000)

@api_router.post("/products", response_model=ProductInput)
async def create_product(input: ProductInput):
    doc = input.model_dump()
    await db.products.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
    return input

@api_router.patch("/products/{product_id}/stock", response_model=ProductInput)
async def adjust_stock(product_id: str, input: StockAdjustment):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    product["stock"] = max(0, int(product.get("stock", 0)) + input.quantity)
    await db.products.update_one({"id": product_id}, {"$set": {"stock": product["stock"]}})
    return ProductInput(**product)

@api_router.get("/expenses", response_model=List[ExpenseInput])
async def list_expenses():
    return await db.expenses.find({}, {"_id": 0}).sort("date", -1).to_list(1000)

@api_router.post("/expenses", response_model=ExpenseInput)
async def create_expense(input: ExpenseInput):
    doc = input.model_dump()
    await db.expenses.insert_one(doc)
    return input

@api_router.post("/sales", response_model=SaleInput)
async def create_sale(input: SaleInput):
    doc = input.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.sales.insert_one(doc)
    for line in input.lines:
        await db.products.update_one({"id": line.product_id}, {"$inc": {"stock": -line.quantity}})
    return input

@api_router.get("/dashboard")
async def dashboard_summary():
    sales = await db.sales.find({}, {"_id": 0, "total": 1, "subtotal": 1}).to_list(1000)
    expenses = await db.expenses.find({}, {"_id": 0, "amount": 1}).to_list(1000)
    return {"sales_total": sum(item.get("total", 0) for item in sales), "expense_total": sum(item.get("amount", 0) for item in expenses), "transaction_count": len(sales)}

@api_router.post("/auth/login")
async def login(input: LoginInput, response: Response):
    user = await db.users.find_one({"email": input.email.lower()}, {"_id": 0})
    if not user or not bcrypt.checkpw(input.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Email atau password salah")
    response.set_cookie("access_token", token_for(user), httponly=True, secure=True, samesite="none", max_age=1800)
    response.set_cookie("refresh_token", token_for(user, "refresh"), httponly=True, secure=True, samesite="none", max_age=604800)
    return public_user(user)

@api_router.get("/auth/me")
async def me(user=Depends(current_user)):
    return public_user(user)

@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}

@api_router.get("/outlets", response_model=List[OutletInput])
async def list_outlets(user=Depends(current_user)):
    return await db.outlets.find({}, {"_id": 0}).to_list(100)

@api_router.post("/outlets", response_model=OutletInput)
async def create_outlet(input: OutletInput, user=Depends(require_roles("Super Admin"))):
    await db.outlets.insert_one(input.model_dump())
    return input

@api_router.post("/settings/qris")
async def save_qris(input: QrisInput, user=Depends(require_roles("Super Admin", "Merchant Admin"))):
    await db.settings.update_one({"outlet_id": input.outlet_id}, {"$set": input.model_dump()}, upsert=True)
    return {"ok": True, "outlet_id": input.outlet_id}

@api_router.post("/self-order", response_model=SelfOrderInput)
async def create_self_order(input: SelfOrderInput):
    doc = input.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["status"] = "Menunggu kasir"
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.self_orders.insert_one(doc)
    return input

@api_router.get("/vendor/orders")
async def vendor_orders(user=Depends(require_roles("Vendor", "Merchant Admin", "Super Admin"))):
    return await db.self_orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)

@api_router.patch("/vendor/orders/{order_id}")
async def update_vendor_order(order_id: str, status: str, user=Depends(require_roles("Vendor", "Merchant Admin", "Super Admin"))):
    await db.self_orders.update_one({"id": order_id}, {"$set": {"status": status}})
    return {"id": order_id, "status": status}

@api_router.get("/vendor/settlement")
async def vendor_settlement(user=Depends(require_roles("Vendor", "Merchant Admin", "Super Admin"))):
    orders = await db.self_orders.find({}, {"_id": 0, "total": 1}).to_list(1000)
    gross = sum(item.get("total", 0) for item in orders)
    commission = round(gross * 0.1)
    return {"gross": gross, "commission": commission, "net": gross - commission, "payout_status": "Siap dicairkan"}

@app.on_event("startup")
async def seed_demo_data():
    await db.users.create_index("email", unique=True)
    await db.self_orders.create_index("created_at")
    for email, password, role, name in DEMO_USERS:
        user = await db.users.find_one({"email": email}, {"_id": 0})
        if not user:
            await db.users.insert_one({"id": str(uuid.uuid4()), "email": email, "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), "role": role, "name": name, "outlet_id": "outlet-sudirman"})
    if await db.outlets.count_documents({}) == 0:
        await db.outlets.insert_many([{"id": "outlet-sudirman", "name": "Outlet Sudirman", "address": "Jl. Sudirman No. 10", "active": True}, {"id": "outlet-kemang", "name": "Outlet Kemang", "address": "Jl. Kemang Raya No. 3", "active": True}])

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()