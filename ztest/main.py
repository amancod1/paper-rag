from fastapi import FastAPI
from paper_backend import router

app = FastAPI()

app.include_router(router)

@app.get('/')
def home():
    return {'msg': 'home'}