from aiogram import Router, types


from modules.database.database import Database
from config import DATABASE_URL
import keyboards as kb

db = Database(DATABASE_URL)

router = Router()


