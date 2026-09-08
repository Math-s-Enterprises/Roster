import bcrypt
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
new_hash = bcrypt.hashpw(b"test1234", bcrypt.gensalt()).decode()

result = client["roster_dev"].users.update_one(
    {"email": "adarshthimmapurmath@gmail.com"},
    {"$set": {"password_hash": new_hash}},
)
print("matched:", result.matched_count, "modified:", result.modified_count)