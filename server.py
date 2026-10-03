from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

# Подключаем статические файлы (CSS, JS)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

@app.get("/")
def read_index():
    return FileResponse("frontend/templates/index.html")