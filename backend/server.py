from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone


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